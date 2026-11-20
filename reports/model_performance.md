# Model performance (held-out 20% test set)

| Condition | Dataset | Model | ROC-AUC | PR-AUC | Brier (calibrated) | Brier (no skill) | Positive rate |
|---|---|---|---|---|---|---|---|
| Diabetes or prediabetes | brfss2015 | gradient_boosting | 0.8243 | 0.4203 | 0.0978 | 0.1199 | 0.1393 |
| High blood pressure | brfss2015 | gradient_boosting | 0.8058 | 0.7476 | 0.1773 | 0.245 | 0.429 |
| High cholesterol | brfss2015 | gradient_boosting | 0.7362 | 0.6537 | 0.2041 | 0.2442 | 0.4241 |
| Heart disease (CHD / heart attack) | brfss2020 | logistic_regression | 0.8363 | 0.3444 | 0.0657 | 0.0783 | 0.0856 |
| Stroke | brfss2020 | logistic_regression | 0.8241 | 0.1641 | 0.0336 | 0.0363 | 0.0377 |
| Kidney disease | brfss2020 | logistic_regression | 0.8005 | 0.1594 | 0.033 | 0.0355 | 0.0368 |

Brier score: lower is better; a useful model must beat the no-skill value.
Calibration plots: reports/calibration_<condition>.png