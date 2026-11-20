"""
Plan recommendation engine.

1. Risk:        risk.assess() gives P(condition) for the user.
2. Simulation:  Monte Carlo over N simulated futures (default 20,000) for a horizon of H years:
                which conditions the user has, which hospitalisations happen, what they cost.
3. Claims:      every plan's rules are applied to the same simulated bills:
                pre-existing disease (PED) waiting period, co-pay, room-rent deduction,
                cardiac sub-limit, deductible (top-up), sum insured cap, OPD cover,
                plus any existing (e.g. employer) cover.
4. Score:       score = E[total cost] + lambda * (CVaR95[total cost] - E[total cost])
                CVaR95 = average total cost in the worst 5% of simulated futures
                total cost = premiums + out-of-pocket spending over the horizon
                lambda reflects risk tolerance (how much the user fears a bad year).
5. Rank:        eligible plans by score (lower is better); explain each.

No model is trained here: there is no labelled "best plan" data, so the choice is
made by decision analysis on predicted risk.
"""
import json
from functools import lru_cache

import numpy as np
import pandas as pd

from src.features import ROOT
from src.risk import ORDER, assess

LAMBDA = {"low": 1.0, "medium": 0.5, "high": 0.2}   # risk tolerance -> tail-risk weight


@lru_cache(maxsize=1)
def load_config():
    cost = json.loads((ROOT / "config" / "cost_table.json").read_text())
    rules = json.loads((ROOT / "config" / "plan_rules.json").read_text())
    plans = pd.read_csv(ROOT / "data" / "plans.csv")
    plans["cardiac_sublimit_inr"] = plans["cardiac_sublimit_inr"].fillna(0)
    return cost, rules, plans


def _lookup(table, age):
    for lo, hi, v in table:
        if lo <= age <= hi:
            return v
    return table[-1][2]


def cvar95(x: np.ndarray) -> float:
    """Expected value of the worst 5% of outcomes (conditional value at risk)."""
    cut = np.percentile(x, 95)
    return float(x[x >= cut].mean())


def premium(plan, age: int, has_ped: bool, smoker: bool, rules) -> float:
    if plan.plan_type == "senior":
        factor = _lookup(rules["senior_plan_age_factors"], age)
    else:
        factor = _lookup(rules["premium_age_factors"], age)
    p = plan.base_premium_inr * factor
    if has_ped:
        p *= 1 + plan.ped_premium_loading_pct / 100
    if smoker:
        p *= 1 + rules["smoker_premium_loading_pct"] / 100
    return p * (1 + rules["gst_pct"] / 100)


def simulate_costs(probs: dict, declared: dict, age: int, years: int, n: int, seed: int = 7):
    """Simulate medical bills. Returns per-condition hospital bills (n, years) and OPD bills."""
    cost, _, _ = load_config()
    rng = np.random.default_rng(seed)
    hosp = {}
    opd = np.zeros((n, years))
    for c in ORDER:
        cc = cost["conditions"][c]
        has = rng.random(n) < probs[c]
        event = has[:, None] & (rng.random((n, years)) < cc["annual_hosp_prob"])
        s = cc["hosp_cost_sigma"]
        amt = rng.lognormal(np.log(cc["hosp_cost_mean_inr"]) - s * s / 2, s, (n, years))
        hosp[c] = np.where(event, amt, 0.0)
        opd += has[:, None] * cc["annual_opd_cost_inr"]
    b = cost["baseline"]
    pb = np.array([_lookup(b["annual_hosp_prob_by_age"], age + y) for y in range(years)])
    s = b["hosp_cost_sigma"]
    amt = rng.lognormal(np.log(b["hosp_cost_mean_inr"]) - s * s / 2, s, (n, years))
    hosp["baseline"] = np.where(rng.random((n, years)) < pb, amt, 0.0)
    return hosp, opd


def evaluate_plan(plan, hosp, opd, declared, age, smoker, existing_cover, rules, years):
    cost, _, _ = load_config()
    ped = [c for c in ORDER if declared.get(c) == 1.0]
    deduct = rules["room_rent_cap_proportionate_deduction_pct"] / 100 if plan.room_rent_capped else 0.0
    n = opd.shape[0]
    bills = np.zeros((n, years))
    claimable = np.zeros((n, years))
    ped_uncovered = np.zeros((n, years))
    for c, amt in hosp.items():
        bills += amt
        cl = amt * (1 - deduct)
        if c != "baseline" and cost["conditions"][c]["cardiac"] and plan.cardiac_sublimit_inr > 0:
            cl = np.minimum(cl, plan.cardiac_sublimit_inr)
        if c in ped:
            for y in range(years):
                if y + 1 <= plan.ped_wait_years:
                    ped_uncovered[:, y] += amt[:, y]
                    cl[:, y] = 0.0
        claimable += cl
    claimable *= 1 - plan.copay_pct / 100
    plan_pays = np.minimum(plan.sum_insured, np.maximum(0.0, claimable - plan.deductible_inr))
    existing_pays = np.minimum(bills, existing_cover)
    hosp_oop = bills - np.minimum(bills, plan_pays + existing_pays)
    opd_oop = opd - np.minimum(opd, plan.opd_cover_inr)
    prem = np.array([premium(plan, age + y, bool(ped), smoker, rules) for y in range(years)])
    total = prem.sum() + (hosp_oop + opd_oop).sum(axis=1)
    return {
        "premium_year1": float(prem[0]),
        "premium_total": float(prem.sum()),
        "expected_out_of_pocket": float((hosp_oop + opd_oop).sum(axis=1).mean()),
        "expected_total_cost": float(total.mean()),
        "cvar95_total_cost": cvar95(total),
        "expected_ped_uncovered": float(ped_uncovered.sum(axis=1).mean()),
        "prob_bill_over_1L_uncovered_any_year": float(((hosp_oop + opd_oop) > 100000).any(axis=1).mean()),
    }


def explain(plan, ev, declared, probs, ped_labels):
    reasons = []
    if ped_labels:
        if plan.ped_wait_years == 0:
            reasons.append(f"Covers your declared {', '.join(ped_labels)} from day 1.")
        else:
            verb = "is" if len(ped_labels) == 1 else "are"
            reasons.append(f"Your declared {', '.join(ped_labels)} {verb} not covered for the first "
                           f"{plan.ped_wait_years} year(s): about Rs {ev['expected_ped_uncovered']:,.0f} "
                           f"of expected bills fall on you in that period.")
    if plan.copay_pct:
        reasons.append(f"You pay {plan.copay_pct:.0f}% of every claim (co-pay).")
    if plan.room_rent_capped:
        reasons.append("Room rent is capped; a costlier room reduces the whole claim proportionately.")
    if plan.cardiac_sublimit_inr and probs["heart_disease"] > 0.05:
        reasons.append(f"Heart treatment is limited to Rs {plan.cardiac_sublimit_inr:,.0f}, and your estimated "
                       f"heart-disease risk is {100 * probs['heart_disease']:.0f}%.")
    if plan.deductible_inr:
        reasons.append(f"Pays only after Rs {plan.deductible_inr:,.0f} of bills in a year (top-up).")
    if plan.opd_cover_inr:
        reasons.append(f"Includes Rs {plan.opd_cover_inr:,.0f}/year outpatient (OPD) cover.")
    return reasons


def plan_risk_eligibility(plan, conditions):
    """Apply a sample-plan matching rule, not a clinical risk classification."""
    measure = getattr(plan, "risk_condition", "highest")
    if measure == "highest":
        probability = max(item["probability"] for item in conditions.values())
        label = "Highest condition probability"
    else:
        probability = conditions[measure]["probability"]
        label = conditions[measure]["label"]
    # Model probabilities use four decimal places; percentage precision is two.
    value = round(100 * probability, 2)
    minimum = float(getattr(plan, "min_risk_pct", 0))
    maximum = float(getattr(plan, "max_risk_pct", 100))
    return {"measure": measure, "label": label, "assessed_pct": value,
            "min_pct": minimum, "max_pct": maximum,
            "eligible": minimum <= value <= maximum}


def recommend(q: dict, prefs: dict, n_sims: int = 20000, plan_config=None) -> dict:
    cost, rules, plans = load_config()
    if plan_config is not None:
        rules, plans = plan_config
    risk = assess(q)
    conds = risk["conditions"]
    probs = {c: conds[c]["probability"] for c in ORDER}
    declared = {c: (1.0 if conds[c]["status"] == "declared" else 0.0) for c in ORDER}
    ped_labels = [conds[c]["label"].lower() for c in ORDER if declared[c] == 1.0]
    age, years = q["age"], int(prefs.get("horizon_years", 5))
    smoker = bool(q["smoked_100_cigarettes"])
    existing = float(prefs.get("existing_cover_inr", 0) or 0)
    lam = LAMBDA[prefs.get("risk_tolerance", "medium")]
    budget = prefs.get("annual_budget_inr")
    min_si = float(prefs.get("min_sum_insured_inr", 0) or 0)

    hosp, opd = simulate_costs(probs, declared, age, years, n_sims)
    no_ins_total = (sum(hosp.values()) + opd).sum(axis=1)
    no_ins_existing = (sum(hosp.values()) - np.minimum(sum(hosp.values()), existing) + opd).sum(axis=1)

    rows, excluded = [], []
    for plan in plans.itertuples():
        why_not = []
        risk_match = plan_risk_eligibility(plan, conds)
        if not risk_match["eligible"]:
            why_not.append(
                f"{risk_match['label']} {risk_match['assessed_pct']:g}% is outside "
                f"this plan's allowed risk range {risk_match['min_pct']:g}-{risk_match['max_pct']:g}%"
            )
        if not plan.min_entry_age <= age <= plan.max_entry_age:
            why_not.append(f"entry age {plan.min_entry_age}-{plan.max_entry_age}")
        if plan.sum_insured < min_si:
            why_not.append("sum insured below your minimum")
        if plan.plan_type == "topup" and existing < plan.deductible_inr * 0.5 and not prefs.get("allow_topup_without_base"):
            why_not.append("top-up needs an existing base cover")
        ev = evaluate_plan(plan, hosp, opd, declared, age, smoker, existing, rules, years)
        if budget and ev["premium_year1"] > float(budget):
            why_not.append(f"premium Rs {ev['premium_year1']:,.0f} above budget")
        if why_not:
            excluded.append({"plan_id": plan.plan_id, "plan_name": plan.plan_name, "reasons": why_not})
            continue
        score = ev["expected_total_cost"] + lam * (ev["cvar95_total_cost"] - ev["expected_total_cost"])
        rows.append({
            "plan_id": plan.plan_id, "plan_name": plan.plan_name, "plan_type": plan.plan_type,
            "sum_insured": int(plan.sum_insured), "score": float(score), **ev,
            "description": plan.description,
            "risk_eligibility": risk_match,
            "notes": explain(plan, ev, declared, probs, ped_labels),
        })
    rows.sort(key=lambda r: r["score"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    summary = None
    if rows:
        best = rows[0]
        cheapest = min(rows, key=lambda r: r["premium_year1"])
        summary = {
            "best_plan": best["plan_name"],
            "expected_total_cost_best": best["expected_total_cost"],
            "expected_total_cost_no_new_insurance": float(no_ins_existing.mean()),
            "cvar95_total_cost_no_new_insurance": cvar95(no_ins_existing),
            "cheapest_premium_plan": cheapest["plan_name"],
            "best_vs_cheapest_extra_premium": best["premium_year1"] - cheapest["premium_year1"],
            "best_vs_cheapest_expected_saving": cheapest["expected_total_cost"] - best["expected_total_cost"],
        }
    return {
        "risk": risk,
        "settings": {"horizon_years": years, "simulations": n_sims, "risk_tolerance": prefs.get("risk_tolerance", "medium"),
                     "lambda": lam, "existing_cover_inr": existing},
        "expected_medical_bills_total": float(no_ins_total.mean()),
        "recommendations": rows[:3],
        "all_eligible_plans": rows,
        "excluded_plans": excluded,
        "summary": summary,
        "disclaimer": ("Decision-support prototype. Plans are sample plans with typical Indian policy structures, "
                       "not real products; cost figures are illustrative assumptions. Not insurance advice."),
    }
