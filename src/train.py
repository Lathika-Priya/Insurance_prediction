"""
Train one calibrated risk model per condition.

For each condition:
  1. Load its dataset (BRFSS 2015 or 2020) and keep questionnaire-answerable features only.
  2. Stratified 80/20 train/test split.
  3. Compare Logistic Regression and Histogram Gradient Boosting (5-fold CV AUC on train).
  4. Calibrate the better model with isotonic regression (3-fold CalibratedClassifierCV).
  5. Evaluate on the held-out test set: ROC-AUC, PR-AUC, Brier score, calibration table.
  6. Save model + metadata (mean predicted probability, used for prevalence adjustment).

Usage:  python -m src.train            (all models)
        python -m src.train diabetes   (one model)
Output: models/<name>.joblib, reports/metrics.json, reports/calibration_<name>.png
"""
import json
import sys
import time

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.features import MODELS, ROOT, load_dataset

MODELS_DIR = ROOT / "models"
REPORTS = ROOT / "reports"
SEED = 42


def candidates():
    return {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0)),
        "gradient_boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                                            max_leaf_nodes=31, l2_regularization=1.0,
                                                            random_state=SEED),
    }


def train_one(name: str, spec: dict, data_cache: dict) -> dict:
    t0 = time.time()
    if spec["dataset"] not in data_cache:
        data_cache[spec["dataset"]] = load_dataset(spec["dataset"])
    df = data_cache[spec["dataset"]]
    X = df[spec["features"]].astype(float)
    y = df[spec["target"]].astype(int)
    if spec["target"] == "Diabetic":
        y = (df[spec["target"]] > 0).astype(int)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=SEED)

    # model selection on a training subsample (speed); final fit on full training set
    sub = X_tr.sample(min(60000, len(X_tr)), random_state=SEED).index
    cv_auc = {}
    for cname, est in candidates().items():
        cv_auc[cname] = float(cross_val_score(est, X_tr.loc[sub], y_tr.loc[sub], cv=5, scoring="roc_auc").mean())
    best = max(cv_auc, key=cv_auc.get)

    model = CalibratedClassifierCV(candidates()[best], method="isotonic", cv=3)
    model.fit(X_tr, y_tr)

    p_te = model.predict_proba(X_te)[:, 1]
    raw = candidates()[best].fit(X_tr, y_tr)
    p_raw = raw.predict_proba(X_te)[:, 1]
    frac_pos, mean_pred = calibration_curve(y_te, p_te, n_bins=10, strategy="quantile")

    metrics = {
        "condition": name, "label": spec["label"], "dataset": spec["dataset"], "target": spec["target"],
        "features": spec["features"], "n_train": int(len(X_tr)), "n_test": int(len(X_te)),
        "positive_rate_train": round(float(y_tr.mean()), 4),
        "cv_auc_candidates": {k: round(v, 4) for k, v in cv_auc.items()},
        "selected_model": best,
        "test_roc_auc": round(float(roc_auc_score(y_te, p_te)), 4),
        "test_pr_auc": round(float(average_precision_score(y_te, p_te)), 4),
        "test_brier_calibrated": round(float(brier_score_loss(y_te, p_te)), 4),
        "test_brier_uncalibrated": round(float(brier_score_loss(y_te, p_raw)), 4),
        "brier_no_skill": round(float(y_te.mean() * (1 - y_te.mean())), 4),
        "calibration_table": [{"mean_predicted": round(float(a), 4), "observed_rate": round(float(b), 4)}
                              for a, b in zip(mean_pred, frac_pos)],
        "mean_predicted_probability": float(model.predict_proba(X)[:, 1].mean()),
        "train_seconds": round(time.time() - t0, 1),
    }
    joblib.dump({"model": model, "features": spec["features"], "meta": metrics}, MODELS_DIR / f"{name}.joblib",
                compress=3)
    plot_calibration(name, spec["label"], mean_pred, frac_pos, metrics)
    print(f"{name:15s} {best:20s} AUC={metrics['test_roc_auc']:.3f} Brier={metrics['test_brier_calibrated']:.4f} "
          f"({metrics['train_seconds']}s)")
    return metrics


def plot_calibration(name, label, mean_pred, frac_pos, m):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
    ax.plot(mean_pred, frac_pos, "o-", label=f"Model (AUC {m['test_roc_auc']:.3f})")
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed rate (test set)")
    ax.set_title(label, fontsize=10)
    lim = max(0.05, float(max(mean_pred.max(), frac_pos.max())) * 1.1)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(REPORTS / f"calibration_{name}.png", dpi=120)
    plt.close(fig)


def main():
    MODELS_DIR.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    names = sys.argv[1:] or list(MODELS)
    path = REPORTS / "metrics.json"
    all_metrics = json.loads(path.read_text()) if path.exists() else {}
    cache = {}
    for n in names:
        all_metrics[n] = train_one(n, MODELS[n], cache)
    path.write_text(json.dumps(all_metrics, indent=2))
    write_markdown(all_metrics)


def write_markdown(all_metrics):
    lines = ["# Model performance (held-out 20% test set)", "",
             "| Condition | Dataset | Model | ROC-AUC | PR-AUC | Brier (calibrated) | Brier (no skill) | Positive rate |",
             "|---|---|---|---|---|---|---|---|"]
    for m in all_metrics.values():
        lines.append(f"| {m['label']} | {m['dataset']} | {m['selected_model']} | {m['test_roc_auc']} | "
                     f"{m['test_pr_auc']} | {m['test_brier_calibrated']} | {m['brier_no_skill']} | "
                     f"{m['positive_rate_train']} |")
    lines += ["", "Brier score: lower is better; a useful model must beat the no-skill value.",
              "Calibration plots: reports/calibration_<condition>.png"]
    (REPORTS / "model_performance.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
