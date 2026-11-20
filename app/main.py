"""
FastAPI backend.

Run from the project root:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Literal, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request as HttpRequest  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.recommend import recommend  # noqa: E402
from app.auth import database, current_session, init_db, require_csrf, require_user, router as auth_router  # noqa: E402

from app.admin import init_catalog, prediction_catalog, catalog_snapshot, router as admin_router

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
    annual_budget_inr: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    min_sum_insured_inr: Optional[float] = Field(default=0, ge=0, allow_inf_nan=False)
    existing_cover_inr: Optional[float] = Field(default=0, ge=0, allow_inf_nan=False)
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    horizon_years: int = Field(default=5, ge=1, le=10)


class Request(BaseModel):
    questionnaire: Questionnaire
    preferences: Preferences = Field(default_factory=Preferences)


@asynccontextmanager
async def lifespan(app):
    init_db()
    init_catalog()
    yield


app = FastAPI(title="AI Health Insurance Assessment", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)


@app.middleware("http")
async def security_headers(request: HttpRequest, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    # The generated API documentation includes its own CDN scripts.
    if request.url.path not in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
    return response


@app.get("/", include_in_schema=False)
def index(request: HttpRequest):
    user = current_session(request)
    return RedirectResponse(("/admin" if user["role"] == "admin" else "/home") if user else "/login", status_code=303)


@app.get("/admin/login", include_in_schema=False)
@app.get("/login", include_in_schema=False)
@app.get("/register", include_in_schema=False)
def auth_page(request: HttpRequest):
    user = current_session(request)
    if user:
        return RedirectResponse("/admin" if user["role"] == "admin" else "/home", status_code=303)
    return FileResponse(ROOT / "app" / "templates" / "auth.html")


@app.get("/admin", include_in_schema=False)
def admin_page(request: HttpRequest):
    user = current_session(request)
    if not user:
        return RedirectResponse("/admin/login", status_code=303)
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return FileResponse(ROOT / "app/templates/admin.html")


@app.get("/profile", include_in_schema=False)
def profile_page(request: HttpRequest):
    if not current_session(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(ROOT / "app/templates/profile.html")


@app.get("/home", include_in_schema=False)
def home(request: HttpRequest):
    user = current_session(request)
    if user and user["role"] == "admin":
        return RedirectResponse("/admin", status_code=303)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(ROOT / "app" / "templates" / "home.html")


@app.get("/api/assessments/latest")
def latest_assessment(user=Depends(require_user)):
    with database() as db:
        row = db.execute(
            "SELECT result_json, completed_at FROM latest_assessments WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    return {"assessment": {
        "result": json.loads(row["result_json"]), "completed_at": row["completed_at"]
    } if row else None}


@app.get("/assessment", include_in_schema=False)
def assessment(request: HttpRequest):
    if not current_session(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(ROOT / "app" / "templates" / "index.html")


@app.get("/static/index.html", include_in_schema=False)
def legacy_index():
    return RedirectResponse("/", status_code=303)


app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


@app.post("/api/recommend")
def api_recommend(req: Request, user=Depends(require_csrf)):
    result = recommend(req.questionnaire.model_dump(), req.preferences.model_dump(), plan_config=prediction_catalog())
    with database() as db:
        db.execute(
            """INSERT INTO latest_assessments (user_id, result_json, completed_at)
               VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
               result_json = excluded.result_json, completed_at = excluded.completed_at""",
            (user["id"], json.dumps(result), datetime.now(timezone.utc).isoformat()),
        )
    return result


@app.get("/api/plans")
def api_plans(user=Depends(require_user)):
    return catalog_snapshot()[1]


@app.get("/api/model-performance")
def api_metrics(user=Depends(require_user)):
    m = json.loads((ROOT / "reports" / "metrics.json").read_text())
    keep = ["label", "dataset", "selected_model", "test_roc_auc", "test_pr_auc", "test_brier_calibrated",
            "brier_no_skill", "n_train", "n_test"]
    return {k: {f: v[f] for f in keep} for k, v in m.items()}
