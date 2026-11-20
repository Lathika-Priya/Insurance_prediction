"""
FastAPI backend.

Run from the project root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000
"""
import json
import sys
from pathlib import Path
from typing import Literal, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.recommend import recommend  # noqa: E402

YesNoUnknown = Literal["yes", "no", "unknown"]


class Questionnaire(BaseModel):
    age: int = Field(ge=18, le=90)
    sex: Literal["male", "female"]
    height_cm: float = Field(ge=120, le=220)
    weight_kg: float = Field(ge=30, le=250)
    smoked_100_cigarettes: bool = Field(description="Smoked at least 100 cigarettes in entire life (BRFSS wording)")
    heavy_alcohol: bool = Field(description="Men >14 drinks/week, women >7 drinks/week")
    physically_active: bool = Field(description="Any physical activity/exercise in past 30 days, outside job")
    fruit_daily: bool
    vegetables_daily: bool
    sleep_hours: float = Field(ge=1, le=24)
    general_health: int = Field(ge=1, le=5, description="1 excellent, 2 very good, 3 good, 4 fair, 5 poor")
    poor_physical_health_days: int = Field(ge=0, le=30)
    poor_mental_health_days: int = Field(ge=0, le=30)
    difficulty_walking: bool
    high_bp: YesNoUnknown
    high_chol: YesNoUnknown
    diabetes: Literal["yes", "no", "borderline", "unknown"]
    heart_disease: bool
    stroke: bool
    asthma: bool
    kidney_disease: bool
    skin_cancer: bool


class Preferences(BaseModel):
    annual_budget_inr: Optional[float] = None
    min_sum_insured_inr: Optional[float] = 0
    existing_cover_inr: Optional[float] = 0
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    horizon_years: int = Field(default=5, ge=1, le=10)


class Request(BaseModel):
    questionnaire: Questionnaire
    preferences: Preferences = Preferences()


app = FastAPI(title="AI Health Insurance Assessment")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.post("/api/recommend")
def api_recommend(req: Request):
    return recommend(req.questionnaire.model_dump(), req.preferences.model_dump())


@app.get("/api/plans")
def api_plans():
    return pd.read_csv(ROOT / "data" / "plans.csv").fillna("").to_dict(orient="records")


@app.get("/api/model-performance")
def api_metrics():
    m = json.loads((ROOT / "reports" / "metrics.json").read_text())
    keep = ["label", "dataset", "selected_model", "test_roc_auc", "test_pr_auc", "test_brier_calibrated",
            "brier_no_skill", "n_train", "n_test"]
    return {k: {f: v[f] for f in keep} for k, v in m.items()}
