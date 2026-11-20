# AI-Based Health Insurance Assessment System

A user answers a health and lifestyle questionnaire. The system estimates their risk of six chronic conditions with machine-learning models, simulates their medical bills over the coming years, applies each insurance plan's rules to those bills, and recommends the plan with the best balance of cost and protection.

```
Questionnaire ─► Risk models (supervised ML) ─► Monte Carlo cost simulation ─► Plan rules ─► Ranked plans + explanations
```

## Quick start

Requires Python 3.10+.

```bash
# macOS / Linux
./run.sh
# Windows
run.bat
```

Then open http://127.0.0.1:8000. Create an account, or sign in with the email and password you registered. A successful registration or login opens the home page.

Manual steps:

```bash
pip install -r requirements.txt
python -m src.validate_data     # optional: data validation report (~1 min)
python -m src.train             # retrain all six models (~1 min); trained models are already included
python -m tests.test_system     # sanity tests + case-study report
uvicorn app.main:app --reload   # web app on http://127.0.0.1:8000
```

The included models were trained with scikit-learn 1.9. If loading fails on your version, run `python -m src.train` (`run.sh` does this automatically).

## Accounts and frontend

The app includes responsive sign-in and registration pages, a five-step health questionnaire, and styled recommendation results. Your name and email appear in the dashboard header. Use **Sign out** to revoke the current session.

- There are no default or shared credentials. Create your own account at `/register`.
- Passwords are salted and hashed with scrypt. Accounts and hashed session tokens are stored in `data/auth.sqlite3`, created automatically on startup and excluded from Git.
- The default browser session expires on the server after 12 hours. **Keep me signed in** uses a seven-day cookie and server session.
- Assessment pages and data APIs require authentication. Mutating authenticated requests also require an `X-CSRF-Token` header, returned by registration, login, and `GET /api/auth/me`.
- The latest completed assessment result is saved per account in SQLite and displayed on the home page after login. New accounts see only the option to take their first assessment. Retaking the test replaces the previous result only after successful completion. Raw questionnaire answers are not stored; refreshing an unfinished questionnaire resets it.
- Optional environment variables: `AUTH_DB_PATH` chooses the SQLite file; `COOKIE_SECURE=1` restricts cookies to HTTPS when deploying behind HTTPS. Leave it unset for local HTTP.
- Email verification and password reset are not included.

Run the authentication integration suite (uses an isolated temporary database and the real prediction API):

```bash
python -m unittest tests.test_auth -v
```

The browser smoke test uses Node 22+ and an installed Chrome or Edge browser (set `CHROME_PATH` if needed). It checks desktop/mobile layouts and the complete registration, assessment, and login flow using a temporary database:

```bash
node tests/browser_smoke.mjs
```

The frontend uses plain HTML, CSS, and JavaScript, served by FastAPI. No npm build or frontend server is needed.

## Project structure

```
insurance-ai/
├── app/
│   ├── main.py               FastAPI backend (POST /api/recommend, GET /api/plans, GET /api/model-performance)
│   ├── templates/            Login/registration and protected questionnaire pages
│   ├── auth.py               SQLite accounts, scrypt passwords, sessions and CSRF
│   └── static/               Shared CSS, JavaScript and favicon (no build step)
├── src/
│   ├── features.py           Feature schema, questionnaire -> dataset encoding
│   ├── validate_data.py      Checks datasets for real signal before training
│   ├── train.py              Trains + calibrates one model per condition
│   ├── risk.py               Inference: chaining, "don't know" handling, prevalence adjustment, risk drivers
│   └── recommend.py          Monte Carlo simulation, plan rules, scoring, explanations
├── config/
│   ├── prevalence.json       Indian prevalence targets (ICMR-INDIAB 2023)
│   ├── cost_table.json       Hospitalisation/OPD cost assumptions per condition  (ILLUSTRATIVE - replace)
│   └── plan_rules.json       Premium age factors, loadings, room-rent deduction
├── data/
│   ├── raw/                  CDC BRFSS 2015 + 2020 (training data)
│   ├── plans.csv             12 sample plans (typical Indian structures; not real products)
│   ├── rejected/             The 3 original project datasets and why they were not used
│   └── README.md             Data sources and column definitions
├── models/                   Trained, calibrated models (.joblib)
├── reports/                  Data validation, model metrics, calibration plots, case studies
└── tests/test_system.py      Sanity tests + case-study generator
```

## How it works

### 1. Questionnaire (22 health questions + 5 preferences)
Every question is something a person can answer without a medical test, worded as in the source survey (e.g. "Have you smoked at least 100 cigarettes in your entire life?" is BRFSS's own definition of a smoker). Diabetes, blood pressure and cholesterol accept "Don't know".

### 2. Risk models (supervised learning)
One binary classifier per condition, trained on the dataset that contains that condition:

| Condition | Dataset | Selected model | Test ROC-AUC | Brier (model / no-skill) |
|---|---|---|---|---|
| Diabetes or prediabetes | BRFSS 2015 (253,680) | Gradient boosting | 0.824 | 0.098 / 0.120 |
| High blood pressure | BRFSS 2015 | Gradient boosting | 0.806 | 0.177 / 0.245 |
| High cholesterol | BRFSS 2015 | Gradient boosting | 0.736 | 0.204 / 0.244 |
| Heart disease | BRFSS 2020 (319,795) | Logistic regression | 0.836 | 0.066 / 0.078 |
| Stroke | BRFSS 2020 | Logistic regression | 0.824 | 0.034 / 0.036 |
| Kidney disease | BRFSS 2020 | Logistic regression | 0.801 | 0.033 / 0.036 |

Per model: stratified 80/20 split; logistic regression vs. histogram gradient boosting compared by 5-fold CV AUC; the winner is **calibrated with isotonic regression** so probabilities are accurate, which is essential because they feed a cost calculation. Full metrics: `reports/metrics.json`, `reports/model_performance.md`, `reports/calibration_*.png`.

**Why separate models, not one merged dataset:** the datasets contain different people, so merging rows would invent fake individuals. Each model learns only from data where its inputs and target were observed together.

**Connecting the models (chaining):** models use other conditions as inputs (e.g. the heart model uses diabetes status). A declared condition is used directly. For "don't know", the model output is averaged over both possibilities, weighted by the predicted probability of that condition. Diabetes, BP and cholesterol depend on each other, so they are solved iteratively until stable.

**Indian prevalence adjustment:** BRFSS is US data. Diabetes (incl. prediabetes), hypertension and high-cholesterol probabilities are shifted on the logit scale so their population average matches ICMR-INDIAB 2023 (26.7%, 35.5%, 24.0%). Heart disease, stroke and kidney disease are not adjusted (no comparable Indian figure configured).

**Risk drivers:** what-if analysis. Each unhealthy habit (smoking, BMI > 25, inactivity, heavy drinking, low fruit/vegetables) is set to the healthy value, and the resulting drop in each risk is reported.

### 3. Cost simulation (Monte Carlo)
20,000 simulated futures over the planning horizon (default 5 years). In each, the user either has or doesn't have each condition (by its probability). Hospitalisations occur by per-condition annual rates, with log-normal costs, plus age-based hospitalisations unrelated to these conditions. Outpatient costs accrue for each condition present. Assumptions are in `config/cost_table.json`.

### 4. Plan rules
The same simulated bills are run through every plan: pre-existing disease waiting period (declared conditions only), co-pay, room-rent proportionate deduction, cardiac sub-limit, top-up deductible, sum-insured cap, OPD cover, existing employer cover. Premiums use age factors, pre-existing disease loading and smoker loading.

### 5. Ranking (decision analysis, no learning)
```
total cost = premiums + out-of-pocket spending over the horizon
score      = E[total cost] + λ × (CVaR95[total cost] − E[total cost])
```
CVaR95 is the average total cost in the worst 5% of futures. λ comes from the user's priority: protection 1.0, balanced 0.5, lowest expected cost 0.2. Plans that fail eligibility (entry age, budget, minimum sum insured, top-up without base cover) are excluded with reasons. Lowest score wins.

**Why no ML for the recommendation itself:** there is no labelled data saying which plan was "best" for a person. Purchase history reflects price and marketing, not suitability. Predicting risk with ML and choosing the plan by explicit cost analysis is transparent and needs no such labels. With real usage data, a learning-to-rank layer could be added later.

## Reports (for the project write-up)

| File | Contents |
|---|---|
| `reports/data_validation.md` | Validation of all 5 datasets, including why the original 3 were dropped |
| `reports/model_performance.md` | Test metrics for all 6 models |
| `reports/calibration_*.png` | Calibration plot per model |
| `reports/case_studies.md` | 6 personas → risk profile → top 3 plans |

## Before final submission: replace the placeholders

1. **`config/cost_table.json`** - every value is an illustrative assumption marked `"source": "TODO"`. Replace with cited Indian figures (NSS 75th round health survey, AB-PMJAY package rates, IRDAI/insurer claim reports, cost-of-illness studies).
2. **`data/plans.csv`** - sample plans. Replace with 15-30 real plans from insurer brochures and policy wordings (same columns).
3. **`config/plan_rules.json`** - premium age factors and loadings are illustrative; calibrate them against real premium tables. Check the GST setting (individual health insurance was made GST-exempt from 22 Sep 2025).

The recommendations are only as good as these inputs. For example, with the current assumptions, a 52-year-old diabetic is recommended a standard plan over the day-1 chronic-care plan, because most diabetes costs are outpatient and the chronic plan's extra premium exceeds the extra hospital cover. With different cost or premium figures, the ranking can change. That is the expected behaviour and worth showing as a sensitivity analysis.

## Limitations

- Training data is US-based; the prevalence shift corrects base rates, not how risk factors combine.
- BRFSS outcomes are self-reported diagnoses (cross-sectional), used as a proxy for current/near-term risk. They are not incidence predictions.
- Undiagnosed conditions are missed when a user answers "No" to a condition they have but don't know about.
- Conditions are simulated independently once their probabilities are set (correlation between them enters only through the model chaining).
- Sample plans and cost figures (see above).
- Single person only; family floater plans are not modelled.
- Decision-support prototype, not regulated insurance advice (IRDAI).

## API example

First register (or use `/api/auth/login` for an existing account), keeping the session cookie:

```bash
curl -c cookies.txt http://127.0.0.1:8000/api/auth/register -H "Content-Type: application/json" -d '{"name":"Your Name","email":"you@example.com","password":"choose-your-own-long-password"}'
```

Copy the returned `csrf_token` into the next request. Treat the cookie file as a credential and remove it when finished.

```bash
curl -b cookies.txt -H "X-CSRF-Token: PASTE_RETURNED_CSRF_TOKEN" -X POST http://127.0.0.1:8000/api/recommend -H "Content-Type: application/json" -d '{
  "questionnaire": {"age": 45, "sex": "male", "height_cm": 172, "weight_kg": 88,
    "smoked_100_cigarettes": true, "heavy_alcohol": false, "physically_active": false,
    "fruit_daily": false, "vegetables_daily": true, "sleep_hours": 6, "general_health": 3,
    "poor_physical_health_days": 2, "poor_mental_health_days": 3, "difficulty_walking": false,
    "high_bp": "unknown", "high_chol": "unknown", "diabetes": "unknown",
    "heart_disease": false, "stroke": false, "asthma": false, "kidney_disease": false, "skin_cancer": false},
  "preferences": {"risk_tolerance": "medium", "horizon_years": 5}
}'
```

Interactive API docs: http://127.0.0.1:8000/docs

## Administrator and profile

Create a separate administrator locally from the project directory:

    python -m app.create_admin

The command prompts for a name, separate email, and password (hidden as you type).
It does not ship a default password or elevate existing user registrations.
Open http://127.0.0.1:8000/admin/login and use those credentials.

The admin dashboard supports adding/editing sample plans, marking plans inactive,
editing age-based pricing multipliers, smoker loading, room-rent deductions and tax,
and resetting user passwords after confirming the administrator password.
Per-plan pre-existing disease loading, waiting periods, co-pay, deductible,
coverage limits and outpatient cover can be edited in the plan form.
At least one plan must remain active.

Both roles have a Profile page with name, email, role, join date, latest assessment
date, and password change. Administrators change their own password here.
Password changes and resets revoke all sessions for that account. Administrators
cannot reset another administrator through the user-reset endpoint.

Managed plans and pricing rules are seeded from the CSV/JSON files once and then
stored in the account SQLite database. Web assessments use the current managed
catalogue without restarting the server. Saved assessments remain snapshots;
users can take a new assessment to see updated pricing. Training and standalone
model checks continue to use the original sample configuration files.
Admin changes are recorded in the local admin_audit table without passwords.

## Profile access and per-plan risk eligibility

Click your account name/avatar at the top right to open your profile, on desktop
or mobile. Separate Profile navigation buttons have been removed.

Each plan's editor includes a risk measure and minimum/maximum allowed percentage.
Choose one of the six modelled conditions or the highest of their probabilities.
A plan is included only when the assessed value falls within its inclusive range,
in addition to existing age, budget, coverage and top-up rules.
Declared conditions count as 100%, matching the existing assessment representation.
The highest condition probability is a matching measure, not a combined disease
probability or clinical risk classification. These thresholds are configurable
sample-plan rules, not validated underwriting criteria.

Existing plans default to highest condition probability with a 0-100% range.
Defaults are applied on read and persisted on the next edit.
Excluded plans show a reason; eligible cards show their risk match.
Saved assessments remain unchanged until the user takes a new assessment.
