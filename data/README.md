# Data

## raw/ (used for training)

| File | Source | Rows | Used for |
|---|---|---|---|
| `brfss2015_diabetes.csv` | CDC Behavioral Risk Factor Surveillance System 2015, cleaned as the Kaggle "Diabetes Health Indicators Dataset" (Alex Teboul), file `diabetes_binary_health_indicators_BRFSS2015.csv` | 253,680 | diabetes, high BP, high cholesterol models |
| `brfss2020_heart.csv` | CDC BRFSS 2020, cleaned as the Kaggle "Personal Key Indicators of Heart Disease" (Kamil Pytlak), file `heart_2020_cleaned.csv` | 319,795 | heart disease, stroke, kidney disease models |

BRFSS is a US telephone health survey run by the CDC. Every column is a survey question, so every model input can be asked in a questionnaire. Cite the CDC BRFSS and the Kaggle compilations in your report.

Excluded columns: Race (sensitive attribute); Income, Education, AnyHealthcare, NoDocbcCost (socio-economic, and unfair to use for insurance decisions); CholCheck (not relevant).

## plans.csv

12 **sample** health insurance plans with structures typical of the Indian market (co-pay, room-rent cap, pre-existing disease waiting period, cardiac sub-limit, OPD cover, top-up deductible, senior plan, chronic-care day-1 cover). Names and premiums are illustrative, not real products. Replace with real plans from insurer brochures and policy wordings for the final version; keep the same columns.

| Column | Meaning |
|---|---|
| plan_type | base, chronic, senior or topup |
| base_premium_inr | annual premium at age 18-35 (age factors in config/plan_rules.json) |
| copay_pct | % of every claim the insured pays |
| deductible_inr | bills per year the insured pays before the plan pays (top-up plans) |
| room_rent_capped | 1 = proportionate deduction applies (config/plan_rules.json) |
| ped_wait_years | years before declared pre-existing diseases are covered |
| ped_premium_loading_pct | premium increase if the user has a pre-existing disease |
| cardiac_sublimit_inr | maximum payout per heart-disease hospitalisation (blank = none) |
| opd_cover_inr | outpatient cover per year |

## rejected/ (the original project datasets, kept for the report)

See `reports/data_validation.md`.

- `hypertension_dataset.csv` - **rejected**: synthetic random data. AUC 0.49-0.50, every feature-target correlation |r| < 0.005, hypertension rate identical for systolic BP >= 140 and < 120, categories split into exact equal shares.
- `cardiac_dataset.csv` - real (Statlog heart, 270 rows) but 8 of 13 features need clinical tests (EKG, stress test, thallium scan, fluoroscopy). Questionnaire-only features reduce its AUC from 0.90 to about 0.72.
- `physiological_dataset.csv` - ward vital signs with a rule-derived risk label (AUC 0.9996). It measures acute hospital deterioration, not insurance risk, and users cannot self-report its inputs.
