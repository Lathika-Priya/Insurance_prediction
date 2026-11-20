"""
Data validation: checks whether a dataset contains real, learnable signal
before any model is trained on it.

Checks
  1. Predictability: cross-validated AUC of logistic regression and gradient boosting.
     ~0.5 means the target is unrelated to the features.
  2. Feature-target correlations: all ~0 is a red flag.
  3. Category balance: categories split into exactly equal shares suggest
     uniform random generation.
  4. Optional clinical-consistency check supplied per dataset.

Usage:  python -m src.validate_data
Writes: reports/data_validation.md and reports/data_validation.json
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.features import ROOT, load_dataset

REPORTS = ROOT / "reports"
SAMPLE = 40000


def check(df: pd.DataFrame, target: str, positive, drop=(), consistency=None, name=""):
    y = (df[target] == positive).astype(int) if positive is not None else df[target].astype(int)
    X = df.drop(columns=[target, *drop])
    X = pd.get_dummies(X, drop_first=True).astype(float).fillna(0)
    if len(X) > SAMPLE:
        idx = X.sample(SAMPLE, random_state=0).index
        X, y = X.loc[idx], y.loc[idx]
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    auc_lr = cross_val_score(lr, X, y, cv=5, scoring="roc_auc").mean()
    auc_gb = cross_val_score(HistGradientBoostingClassifier(), X, y, cv=5, scoring="roc_auc").mean()

    num = df.drop(columns=[target, *drop]).select_dtypes("number")
    yfull = (df[target] == positive).astype(int) if positive is not None else df[target].astype(int)
    corr = {c: round(float(np.corrcoef(num[c], yfull)[0, 1]), 4) for c in num.columns if num[c].std() > 0}
    max_abs_corr = max(abs(v) for v in corr.values()) if corr else 0.0

    uniform_cats = []
    for c in df.drop(columns=[target, *drop]).columns:
        if df[c].nunique() <= 25 and df[c].nunique() >= 2:
            shares = df[c].value_counts(normalize=True)
            if shares.max() - shares.min() < 0.01:
                uniform_cats.append(c)

    result = {
        "dataset": name, "rows": int(len(df)), "target": target,
        "positive_rate": round(float(yfull.mean()), 4),
        "auc_logistic": round(float(auc_lr), 4), "auc_gradient_boosting": round(float(auc_gb), 4),
        "max_abs_feature_target_correlation": round(max_abs_corr, 4),
        "perfectly_uniform_categorical_columns": uniform_cats,
        "consistency_check": consistency(df) if consistency else None,
    }
    best = max(auc_lr, auc_gb)
    if best < 0.55 and max_abs_corr < 0.02:
        result["verdict"] = "REJECT: no learnable signal (looks randomly generated)"
    elif best > 0.99:
        result["verdict"] = "SUSPECT: label almost perfectly predictable (likely computed by a fixed rule)"
    elif best < 0.65:
        result["verdict"] = "WEAK: little signal, use with caution"
    else:
        result["verdict"] = "PASS: real, learnable signal"
    return result


def htn_consistency(df):
    y = df["Hypertension"].astype(str).str.lower().isin(["high", "yes", "1"])
    return {
        "P(hypertension | systolic>=140)": round(float(y[df["Systolic_BP"] >= 140].mean()), 3),
        "P(hypertension | systolic<120)": round(float(y[df["Systolic_BP"] < 120].mean()), 3),
        "note": "Real data: first value should be far higher than second.",
    }


def main():
    REPORTS.mkdir(exist_ok=True)
    results = []

    d15 = load_dataset("brfss2015")
    results.append(check(d15, "Diabetes_binary", None, name="BRFSS 2015 (diabetes) - USED"))
    d20 = load_dataset("brfss2020")
    results.append(check(d20, "HeartDisease", None, name="BRFSS 2020 (heart disease) - USED"))

    rej = ROOT / "data" / "rejected"
    htn = pd.read_csv(rej / "hypertension_dataset.csv")
    results.append(check(htn, "Hypertension", "High", consistency=htn_consistency,
                         name="Hypertension dataset (original project) - REJECTED"))
    card = pd.read_csv(rej / "cardiac_dataset.csv")
    r = check(card, "Heart Disease", "Presence", name="Cardiac dataset (original project) - NOT USED")
    q_cols = ["Age", "Sex", "BP", "Cholesterol", "FBS over 120", "Heart Disease"]
    r_q = check(card[q_cols], "Heart Disease", "Presence", name="cardiac questionnaire-only")
    r["auc_gradient_boosting_questionnaire_features_only"] = r_q["auc_gradient_boosting"]
    r["auc_logistic_questionnaire_features_only"] = r_q["auc_logistic"]
    r["note"] = ("Real data, but only 270 rows and 8 of 13 features need clinical tests "
                 "(EKG, stress test, thallium scan, fluoroscopy) that a questionnaire cannot collect.")
    results.append(r)
    phys = pd.read_csv(rej / "physiological_dataset.csv")
    r = check(phys, "Risk_Level", "High", drop=("Patient_ID",), name="Physiological dataset (original project) - NOT USED")
    r["note"] = ("Ward vital signs (respiratory rate, SpO2, consciousness, oxygen therapy) - an acute "
                 "deterioration score (NEWS2-style), not long-term insurance risk; users cannot self-report these.")
    results.append(r)

    (REPORTS / "data_validation.json").write_text(json.dumps(results, indent=2))
    lines = ["# Data validation report", "",
             "Each dataset was tested for real, learnable signal before use.", ""]
    for r in results:
        lines += [f"## {r['dataset']}", "", f"**Verdict: {r['verdict']}**", ""]
        for k, v in r.items():
            if k not in ("dataset", "verdict"):
                lines.append(f"- {k}: {v}")
        lines.append("")
    (REPORTS / "data_validation.md").write_text("\n".join(lines))
    for r in results:
        print(f"{r['dataset']}: {r['verdict']} (AUC LR {r['auc_logistic']}, GB {r['auc_gradient_boosting']})")


if __name__ == "__main__":
    main()
