# Data validation report

Each dataset was tested for real, learnable signal before use.

## BRFSS 2015 (diabetes) - USED

**Verdict: PASS: real, learnable signal**

- rows: 253680
- target: Diabetes_binary
- positive_rate: 0.1393
- auc_logistic: 0.8256
- auc_gradient_boosting: 0.8282
- max_abs_feature_target_correlation: 0.2936
- perfectly_uniform_categorical_columns: []
- consistency_check: None

## BRFSS 2020 (heart disease) - USED

**Verdict: PASS: real, learnable signal**

- rows: 319795
- target: HeartDisease
- positive_rate: 0.0856
- auc_logistic: 0.8378
- auc_gradient_boosting: 0.8362
- max_abs_feature_target_correlation: 0.2432
- perfectly_uniform_categorical_columns: []
- consistency_check: None

## Hypertension dataset (original project) - REJECTED

**Verdict: REJECT: no learnable signal (looks randomly generated)**

- rows: 174982
- target: Hypertension
- positive_rate: 0.7188
- auc_logistic: 0.4917
- auc_gradient_boosting: 0.498
- max_abs_feature_target_correlation: 0.004
- perfectly_uniform_categorical_columns: ['Country', 'Smoking_Status', 'Physical_Activity_Level', 'Family_History', 'Diabetes', 'Stress_Level', 'Gender', 'Education_Level', 'Employment_Status']
- consistency_check: {'P(hypertension | systolic>=140)': 0.717, 'P(hypertension | systolic<120)': 0.721, 'note': 'Real data: first value should be far higher than second.'}

## Cardiac dataset (original project) - NOT USED

**Verdict: PASS: real, learnable signal**

- rows: 270
- target: Heart Disease
- positive_rate: 0.4444
- auc_logistic: 0.9011
- auc_gradient_boosting: 0.8825
- max_abs_feature_target_correlation: 0.525
- perfectly_uniform_categorical_columns: []
- consistency_check: None
- auc_gradient_boosting_questionnaire_features_only: 0.6847
- auc_logistic_questionnaire_features_only: 0.7211
- note: Real data, but only 270 rows and 8 of 13 features need clinical tests (EKG, stress test, thallium scan, fluoroscopy) that a questionnaire cannot collect.

## Physiological dataset (original project) - NOT USED

**Verdict: SUSPECT: label almost perfectly predictable (likely computed by a fixed rule)**

- rows: 1000
- target: Risk_Level
- positive_rate: 0.279
- auc_logistic: 0.9996
- auc_gradient_boosting: 0.9998
- max_abs_feature_target_correlation: 0.7659
- perfectly_uniform_categorical_columns: []
- consistency_check: None
- note: Ward vital signs (respiratory rate, SpO2, consciousness, oxygen therapy) - an acute deterioration score (NEWS2-style), not long-term insurance risk; users cannot self-report these.
