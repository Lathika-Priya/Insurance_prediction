"""Admin-only catalogue management and authenticated account profiles."""
import csv
import json
import sqlite3
import time
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth import (ROOT, database, hash_password, verify_password, require_user,
                      require_csrf, limit_auth_attempts)

router = APIRouter()


def init_catalog():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS managed_plans (
                plan_id TEXT PRIMARY KEY, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS catalog_settings (
                key TEXT PRIMARY KEY, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_audit (
                id INTEGER PRIMARY KEY, actor_id INTEGER NOT NULL,
                action TEXT NOT NULL, target TEXT NOT NULL, created_at INTEGER NOT NULL
            );
        """)
        if not db.execute("SELECT 1 FROM catalog_settings WHERE key = 'rules'").fetchone():
            rules = json.loads((ROOT / "config/plan_rules.json").read_text())
            db.execute("INSERT INTO catalog_settings VALUES ('rules', ?)", (json.dumps(rules),))
            with (ROOT / "data/plans.csv").open(encoding="utf-8", newline="") as source:
                for row in csv.DictReader(source):
                    row = {key: (value or 0) for key, value in row.items()}
                    row["room_rent_capped"] = bool(int(row["room_rent_capped"]))
                    plan = Plan(**row)
                    db.execute("INSERT OR IGNORE INTO managed_plans VALUES (?, ?)",
                               (plan.plan_id, plan.model_dump_json()))


def catalog_snapshot(active_only=True):
    with database() as db:
        rows = db.execute("SELECT data FROM managed_plans ORDER BY plan_id").fetchall()
        rules = json.loads(db.execute("SELECT data FROM catalog_settings WHERE key='rules'").fetchone()["data"])
    plans = [Plan.model_validate_json(row["data"]).model_dump() for row in rows]
    if active_only:
        plans = [plan for plan in plans if plan["active"]]
    return rules, plans


def prediction_catalog():
    rules, plans = catalog_snapshot()
    return rules, pd.DataFrame(plans)


def require_admin(user=Depends(require_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


def admin_mutation(user=Depends(require_csrf)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


def audit(db, user, action, target):
    db.execute("INSERT INTO admin_audit (actor_id, action, target, created_at) VALUES (?, ?, ?, ?)",
               (user["id"], action, str(target), int(time.time())))


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    plan_name: str = Field(min_length=2, max_length=120)
    plan_type: Literal["base", "chronic", "senior", "topup"]
    sum_insured: int = Field(gt=0, le=100000000)
    base_premium_inr: float = Field(gt=0, le=10000000)
    min_entry_age: int = Field(ge=18, le=90)
    max_entry_age: int = Field(ge=18, le=90)
    copay_pct: float = Field(ge=0, le=100)
    deductible_inr: float = Field(ge=0, le=100000000)
    room_rent_capped: bool
    ped_wait_years: int = Field(ge=0, le=10)
    ped_premium_loading_pct: float = Field(ge=0, le=300)
    cardiac_sublimit_inr: float = Field(ge=0, le=100000000)
    opd_cover_inr: float = Field(ge=0, le=10000000)
    description: str = Field(min_length=2, max_length=1000)
    active: bool = True
    risk_condition: Literal["highest", "diabetes", "high_bp", "high_chol", "heart_disease", "stroke", "kidney_disease"] = "highest"
    min_risk_pct: float = Field(default=0, ge=0, le=100)
    max_risk_pct: float = Field(default=100, ge=0, le=100)

    @model_validator(mode="after")
    def valid_ages(self):
        if self.min_risk_pct > self.max_risk_pct:
            raise ValueError("Minimum risk percentage cannot exceed maximum risk percentage.")
        if self.min_entry_age > self.max_entry_age:
            raise ValueError("Minimum age cannot exceed maximum age.")
        if self.plan_type == "topup" and self.deductible_inr <= 0:
            raise ValueError("A top-up plan needs a positive deductible.")
        return self


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    premium_age_factors: list[tuple[int, int, float]] = Field(min_length=1, max_length=20)
    senior_plan_age_factors: list[tuple[int, int, float]] = Field(min_length=1, max_length=20)
    smoker_premium_loading_pct: float = Field(ge=0, le=300)
    room_rent_cap_proportionate_deduction_pct: float = Field(ge=0, le=100)
    gst_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def contiguous_age_bands(self):
        for table, start in ((self.premium_age_factors, 18), (self.senior_plan_age_factors, 60)):
            expected = start
            for low, high, multiplier in table:
                if low != expected or high < low or high > 120 or not 0 < multiplier <= 20:
                    raise ValueError("Age bands must be contiguous, ordered, and have multipliers above 0 and at most 20.")
                expected = high + 1
            if expected != 121:
                raise ValueError("Age bands must cover through age 120.")
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordReset(BaseModel):
    admin_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/api/profile")
def profile(user=Depends(require_user)):
    with database() as db:
        row = db.execute("SELECT id, name, email, role, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
        assessment = db.execute("SELECT completed_at FROM latest_assessments WHERE user_id = ?", (user["id"],)).fetchone()
    return {**dict(row), "last_assessment_at": assessment["completed_at"] if assessment else None}


@router.post("/api/profile/password", dependencies=[Depends(limit_auth_attempts)])
def change_password(payload: PasswordChange, user=Depends(require_csrf)):
    with database() as db:
        old = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()["password_hash"]
        if not verify_password(payload.current_password, old):
            raise HTTPException(400, "Current password is incorrect.")
        if verify_password(payload.new_password, old):
            raise HTTPException(400, "Choose a password different from your current password.")
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(payload.new_password), user["id"]))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        audit(db, user, "password_changed", user["id"])
    return {"message": "Password changed. Please sign in again."}


@router.get("/api/admin/overview")
def overview(user=Depends(require_admin)):
    rules, plans = catalog_snapshot(False)
    with database() as db:
        counts = {key: db.execute(query).fetchone()[0] for key, query in {
            "users": "SELECT COUNT(*) FROM users WHERE role='user'",
            "assessments": "SELECT COUNT(*) FROM latest_assessments",
        }.items()}
    return {**counts, "active_plans": sum(plan["active"] for plan in plans),
            "plans": plans, "rules": {key: rules[key] for key in Rules.model_fields}}


@router.post("/api/admin/plans", status_code=201)
def add_plan(payload: Plan, user=Depends(admin_mutation)):
    try:
        with database() as db:
            db.execute("INSERT INTO managed_plans VALUES (?, ?)", (payload.plan_id, payload.model_dump_json()))
            audit(db, user, "plan_created", payload.plan_id)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "This plan ID already exists.")
    return payload


@router.put("/api/admin/plans/{plan_id}")
def update_plan(plan_id: str, payload: Plan, user=Depends(admin_mutation)):
    if plan_id != payload.plan_id:
        raise HTTPException(400, "The plan ID cannot be changed.")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM managed_plans WHERE plan_id = ?", (plan_id,)).fetchone():
            raise HTTPException(404, "Plan not found.")
        if not payload.active:
            other = db.execute("SELECT data FROM managed_plans WHERE plan_id != ?", (plan_id,)).fetchall()
            if not any(json.loads(row["data"])["active"] for row in other):
                raise HTTPException(400, "Keep at least one active plan.")
        db.execute("UPDATE managed_plans SET data = ? WHERE plan_id = ?", (payload.model_dump_json(), plan_id))
        audit(db, user, "plan_updated", plan_id)
    return payload


@router.put("/api/admin/rules")
def update_rules(payload: Rules, user=Depends(admin_mutation)):
    with database() as db:
        db.execute("UPDATE catalog_settings SET data = ? WHERE key = 'rules'", (payload.model_dump_json(),))
        audit(db, user, "pricing_rules_updated", "rules")
    return payload


@router.get("/api/admin/users")
def users(user=Depends(require_admin)):
    with database() as db:
        rows = db.execute("""SELECT u.id, u.name, u.email, u.role, u.created_at,
                             a.completed_at AS last_assessment_at
                             FROM users u LEFT JOIN latest_assessments a ON u.id = a.user_id
                             ORDER BY u.created_at DESC, u.id DESC""").fetchall()
    return [dict(row) for row in rows]


@router.post("/api/admin/users/{user_id}/password", dependencies=[Depends(limit_auth_attempts)])
def reset_password(user_id: int, payload: PasswordReset, user=Depends(admin_mutation)):
    with database() as db:
        admin = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not verify_password(payload.admin_password, admin["password_hash"]):
            raise HTTPException(400, "Your administrator password is incorrect.")
        target = db.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Account not found.")
        if target["role"] == "admin":
            raise HTTPException(403, "Administrators change their own password from their profile.")
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(payload.new_password), user_id))
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        audit(db, user, "user_password_reset", user_id)
    return {"message": "Password reset. The user must sign in again."}
