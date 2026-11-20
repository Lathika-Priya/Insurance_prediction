"""
Risk inference: questionnaire answers -> probability of each condition.

- Conditions the user has been diagnosed with are 'declared' (probability 1,
  treated as pre-existing disease for insurance).
- All others are 'estimated' by the calibrated model for that condition.
- Models use other conditions as inputs (e.g. the heart model uses diabetes).
  If the user answered "don't know" for an input condition, the model output is
  averaged over both possibilities, weighted by that condition's own predicted
  probability (marginalisation). Diabetes, blood pressure and cholesterol depend
  on each other, so their estimates are solved iteratively until they settle.
- Finally each probability is shifted to Indian prevalence (config/prevalence.json).
"""
import itertools
import json
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd

from src.features import (CONDITION_COLUMNS, MODELS, MODIFIABLE, ROOT, base_row, bmi, declared_conditions,
                          encode_condition, healthy_bmi_weight, logit, sigmoid)

ORDER = ["diabetes", "high_bp", "high_chol", "heart_disease", "stroke", "kidney_disease"]
MUTUAL = ["diabetes", "high_bp", "high_chol"]   # can be "don't know"


@lru_cache(maxsize=1)
def load_models():
    out = {}
    for name in MODELS:
        path = ROOT / "models" / f"{name}.joblib"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run `python -m src.train` first")
        out[name] = joblib.load(path)
    return out


@lru_cache(maxsize=1)
def prevalence_shift():
    cfg = json.loads((ROOT / "config" / "prevalence.json").read_text())
    models = load_models()
    shift = {}
    for name in MODELS:
        target = cfg.get(name)
        if target is None:
            shift[name] = 0.0
        else:
            mean_pred = models[name]["meta"]["mean_predicted_probability"]
            shift[name] = float(logit(target) - logit(mean_pred))
    return shift


def _predict(name: str, q: dict, cond_inputs: dict) -> float:
    """
    Predict one condition. cond_inputs: condition -> value in [0, 1]
    (0/1 = known, in between = uncertain -> marginalised).
    """
    bundle = load_models()[name]
    spec = MODELS[name]
    ds = spec["dataset"]
    row = base_row(q, ds)
    col_of = {c: col for c, col in CONDITION_COLUMNS[ds].items() if col in spec["features"]}
    uncertain = [c for c in col_of if 0.0 < cond_inputs[c] < 1.0]
    rows, weights = [], []
    for combo in itertools.product([0.0, 1.0], repeat=len(uncertain)):
        r = dict(row)
        w = 1.0
        for c, col in col_of.items():
            if c in uncertain:
                v = combo[uncertain.index(c)]
                w *= cond_inputs[c] if v == 1.0 else 1 - cond_inputs[c]
            else:
                v = round(cond_inputs[c])
            r[col] = encode_condition(c, v, ds)
        rows.append(r)
        weights.append(w)
    X = pd.DataFrame(rows)[bundle["features"]].astype(float)
    p = bundle["model"].predict_proba(X)[:, 1]
    return float(np.dot(p, weights))


def _solve(q: dict) -> dict:
    """Unadjusted (dataset-scale) probability for every condition."""
    declared = declared_conditions(q)
    models = load_models()
    # inputs for chaining: declared value, or starting guess = model's average prediction
    inputs = {c: (declared[c] if declared[c] is not None else models[c]["meta"]["mean_predicted_probability"])
              for c in ORDER}
    unknown = [c for c in MUTUAL if declared[c] is None]
    for _ in range(6):
        new = {c: _predict(c, q, inputs) for c in unknown}
        delta = max([abs(new[c] - inputs[c]) for c in unknown] or [0])
        inputs.update(new)
        if delta < 1e-4:
            break
    raw = {}
    for c in ORDER:
        raw[c] = _predict(c, q, inputs) if declared[c] != 1.0 else 1.0
    return raw, declared


def assess(q: dict, with_drivers: bool = True) -> dict:
    raw, declared = _solve(q)
    shift = prevalence_shift()
    result = {}
    for c in ORDER:
        if declared[c] == 1.0:
            result[c] = {"label": MODELS[c]["label"], "status": "declared", "probability": 1.0}
            continue
        p = float(sigmoid(logit(raw[c]) + shift[c]))
        result[c] = {
            "label": MODELS[c]["label"], "status": "estimated", "probability": round(p, 4),
            "dataset_probability": round(raw[c], 4),
            "answered": "don't know" if declared[c] is None else "no",
        }
    if with_drivers:
        add_drivers(q, result, raw)
    return {"bmi": bmi(q["height_cm"], q["weight_kg"]), "conditions": result}


def add_drivers(q: dict, result: dict, raw: dict):
    """What-if analysis: how much each modifiable habit adds to each estimated risk."""
    changes = []
    for key, (healthy, label) in MODIFIABLE.items():
        if bool(q[key]) != healthy:
            changes.append((label, {**q, key: healthy}))
    if bmi(q["height_cm"], q["weight_kg"]) > 25:
        changes.append(("BMI above 25", {**q, "weight_kg": healthy_bmi_weight(q["height_cm"])}))
    shift = prevalence_shift()
    for label, q2 in changes:
        raw2, _ = _solve(q2)
        for c, r in result.items():
            if r["status"] != "estimated":
                continue
            p_now = sigmoid(logit(raw[c]) + shift[c])
            p_new = sigmoid(logit(raw2[c]) + shift[c])
            diff = float(p_now - p_new)
            if diff > 0.002:
                r.setdefault("drivers", []).append({"factor": label, "adds_percentage_points": round(100 * diff, 1)})
    for r in result.values():
        if "drivers" in r:
            r["drivers"].sort(key=lambda d: -d["adds_percentage_points"])
