"""
Feature schema shared by training and inference.

Every model input is something a user can answer in a questionnaire.
Questionnaire answers are converted into the exact encoding of each
training dataset (CDC BRFSS 2015 and BRFSS 2020), so the model sees
inputs in the same form it was trained on.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
BRFSS2015 = RAW / "brfss2015_diabetes.csv"   # CDC BRFSS 2015, Diabetes Health Indicators (253,680 rows)
BRFSS2020 = RAW / "brfss2020_heart.csv"      # CDC BRFSS 2020, Personal Key Indicators of Heart Disease (319,795 rows)

AGE_2020 = ['18-24', '25-29', '30-34', '35-39', '40-44', '45-49', '50-54',
            '55-59', '60-64', '65-69', '70-74', '75-79', '80 or older']
GENHEALTH_2020 = {'Excellent': 1, 'Very good': 2, 'Good': 3, 'Fair': 4, 'Poor': 5}
# Diabetic in BRFSS 2020 -> ordinal 0 = no, 1 = borderline, 2 = yes
DIABETIC_2020 = {'No': 0, 'Yes (during pregnancy)': 0, 'No, borderline diabetes': 1, 'Yes': 2}

# ---------------------------------------------------------------------------
# Model definitions: which dataset, which target, which questionnaire features
# Sensitive / socio-economic columns (Race, Income, Education, healthcare
# access) are deliberately excluded.
# ---------------------------------------------------------------------------
F2015_BASE = ['BMI', 'Smoker', 'Stroke', 'HeartDiseaseorAttack', 'PhysActivity', 'Fruits',
              'Veggies', 'HvyAlcoholConsump', 'GenHlth', 'MentHlth', 'PhysHlth', 'DiffWalk',
              'Sex', 'Age']
F2020_BASE = ['BMI', 'Smoking', 'AlcoholDrinking', 'PhysicalHealth', 'MentalHealth',
              'DiffWalking', 'Sex', 'AgeCategory', 'Diabetic', 'PhysicalActivity',
              'GenHealth', 'SleepTime', 'Asthma', 'SkinCancer']

MODELS = {
    "diabetes": {
        "label": "Diabetes or prediabetes",
        "dataset": "brfss2015", "target": "Diabetes_binary",
        "features": ['HighBP', 'HighChol'] + F2015_BASE,
    },
    "high_bp": {
        "label": "High blood pressure",
        "dataset": "brfss2015", "target": "HighBP",
        "features": ['HighChol', 'Diabetes_binary'] + F2015_BASE,
    },
    "high_chol": {
        "label": "High cholesterol",
        "dataset": "brfss2015", "target": "HighChol",
        "features": ['HighBP', 'Diabetes_binary'] + F2015_BASE,
    },
    "heart_disease": {
        "label": "Heart disease (CHD / heart attack)",
        "dataset": "brfss2020", "target": "HeartDisease",
        "features": F2020_BASE + ['Stroke', 'KidneyDisease'],
    },
    "stroke": {
        "label": "Stroke",
        "dataset": "brfss2020", "target": "Stroke",
        "features": F2020_BASE + ['HeartDisease', 'KidneyDisease'],
    },
    "kidney_disease": {
        "label": "Kidney disease",
        "dataset": "brfss2020", "target": "KidneyDisease",
        "features": F2020_BASE + ['HeartDisease', 'Stroke'],
    },
}

# Columns in each dataset that correspond to a condition we also model.
# Used to plug in declared answers or predicted probabilities (chaining).
CONDITION_COLUMNS = {
    "brfss2015": {"diabetes": "Diabetes_binary", "high_bp": "HighBP", "high_chol": "HighChol",
                  "heart_disease": "HeartDiseaseorAttack", "stroke": "Stroke"},
    "brfss2020": {"diabetes": "Diabetic", "heart_disease": "HeartDisease", "stroke": "Stroke",
                  "kidney_disease": "KidneyDisease"},
}


def load_dataset(name: str) -> pd.DataFrame:
    """Load a raw dataset and encode every column numerically."""
    if name == "brfss2015":
        return pd.read_csv(BRFSS2015).astype(float)
    if name == "brfss2020":
        d = pd.read_csv(BRFSS2020)
        yn = ['HeartDisease', 'Smoking', 'AlcoholDrinking', 'Stroke', 'DiffWalking',
              'PhysicalActivity', 'Asthma', 'KidneyDisease', 'SkinCancer']
        for c in yn:
            d[c] = (d[c] == 'Yes').astype(float)
        d['Sex'] = (d['Sex'] == 'Male').astype(float)
        d['AgeCategory'] = d['AgeCategory'].map({a: i + 1 for i, a in enumerate(AGE_2020)}).astype(float)
        d['GenHealth'] = d['GenHealth'].map(GENHEALTH_2020).astype(float)
        d['Diabetic'] = d['Diabetic'].map(DIABETIC_2020).astype(float)
        d = d.drop(columns=['Race'])          # sensitive attribute, never used
        return d
    raise ValueError(name)


# ---------------------------------------------------------------------------
# Questionnaire -> dataset encodings
# ---------------------------------------------------------------------------
def age_band(age: int) -> int:
    """BRFSS age code: 1 = 18-24, 2 = 25-29, ... 12 = 75-79, 13 = 80+."""
    if age < 25:
        return 1
    return int(min(13, (age - 25) // 5 + 2))


def bmi(height_cm: float, weight_kg: float) -> float:
    h = height_cm / 100.0
    return round(weight_kg / (h * h), 1)


def base_row(q: dict, dataset: str) -> dict:
    """Map questionnaire answers to one dataset's columns (conditions excluded)."""
    b = bmi(q["height_cm"], q["weight_kg"])
    sex = 1.0 if q["sex"] == "male" else 0.0
    age = float(age_band(q["age"]))
    if dataset == "brfss2015":
        return {
            'BMI': b, 'Smoker': float(q["smoked_100_cigarettes"]),
            'PhysActivity': float(q["physically_active"]), 'Fruits': float(q["fruit_daily"]),
            'Veggies': float(q["vegetables_daily"]), 'HvyAlcoholConsump': float(q["heavy_alcohol"]),
            'GenHlth': float(q["general_health"]), 'MentHlth': float(q["poor_mental_health_days"]),
            'PhysHlth': float(q["poor_physical_health_days"]), 'DiffWalk': float(q["difficulty_walking"]),
            'Sex': sex, 'Age': age,
        }
    return {
        'BMI': b, 'Smoking': float(q["smoked_100_cigarettes"]), 'AlcoholDrinking': float(q["heavy_alcohol"]),
        'PhysicalHealth': float(q["poor_physical_health_days"]),
        'MentalHealth': float(q["poor_mental_health_days"]), 'DiffWalking': float(q["difficulty_walking"]),
        'Sex': sex, 'AgeCategory': age, 'PhysicalActivity': float(q["physically_active"]),
        'GenHealth': float(q["general_health"]), 'SleepTime': float(q["sleep_hours"]),
        'Asthma': float(q["asthma"]), 'SkinCancer': float(q["skin_cancer"]),
    }


def encode_condition(cond: str, value: float, dataset: str) -> float:
    """Encode a 0/1 condition value in a dataset's coding (Diabetic 2020 uses 0/2)."""
    if dataset == "brfss2020" and cond == "diabetes":
        return 2.0 * value
    return float(value)


def declared_conditions(q: dict) -> dict:
    """
    Conditions the user has already been told they have.
    Returns cond -> 1.0 (yes), 0.0 (no) or None (don't know / must be estimated).
    'borderline' diabetes is treated as 'yes' for the diabetes model, whose
    target is prediabetes-or-diabetes.
    """
    tri = {"yes": 1.0, "no": 0.0, "unknown": None, "borderline": 1.0}
    return {
        "diabetes": tri[q["diabetes"]],
        "high_bp": tri[q["high_bp"]],
        "high_chol": tri[q["high_chol"]],
        "heart_disease": 1.0 if q["heart_disease"] else 0.0,
        "stroke": 1.0 if q["stroke"] else 0.0,
        "kidney_disease": 1.0 if q["kidney_disease"] else 0.0,
    }


# Lifestyle changes used for "what drives your risk" explanations
MODIFIABLE = {
    "smoked_100_cigarettes": (False, "Smoking history"),
    "heavy_alcohol": (False, "Heavy alcohol use"),
    "physically_active": (True, "Physical inactivity"),
    "fruit_daily": (True, "Low fruit intake"),
    "vegetables_daily": (True, "Low vegetable intake"),
}


def healthy_bmi_weight(height_cm: float) -> float:
    h = height_cm / 100.0
    return 24.9 * h * h


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))
