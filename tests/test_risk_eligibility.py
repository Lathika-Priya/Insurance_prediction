"""Meaningful boundary and no-match tests for sample-plan risk eligibility."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from src.recommend import load_config, plan_risk_eligibility, recommend
from src.risk import ORDER
from tests.test_system import BASE


class RiskEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.conditions = {name: {"probability": 0.1234, "label": name, "status": "estimated"} for name in ORDER}
        self.conditions["high_bp"]["probability"] = 0.2

    def test_inclusive_bounds_specific_and_highest_measures(self):
        for measure, expected in (("diabetes",12.34), ("highest",20)):
            plan = SimpleNamespace(risk_condition=measure, min_risk_pct=expected, max_risk_pct=expected)
            self.assertTrue(plan_risk_eligibility(plan, self.conditions)["eligible"])
            plan.min_risk_pct = expected + .01
            plan.max_risk_pct = 100
            self.assertFalse(plan_risk_eligibility(plan, self.conditions)["eligible"])
        self.assertTrue(plan_risk_eligibility(SimpleNamespace(), self.conditions)["eligible"])
        self.conditions["diabetes"].update(probability=1, status="declared")
        self.assertEqual(plan_risk_eligibility(SimpleNamespace(), self.conditions)["assessed_pct"], 100)

    def test_no_matching_plan_and_risk_details_in_results(self):
        _, rules, plans = load_config()
        plan = plans[plans.plan_id == "P03"].to_dict("records")[0]
        plan.update(risk_condition="highest", min_risk_pct=0, max_risk_pct=19.99)
        with patch("src.recommend.assess", return_value={"conditions":self.conditions,"bmi":24}):
            result = recommend(BASE, {}, n_sims=100, plan_config=(rules,pd.DataFrame([plan])))
            self.assertIsNone(result["summary"])
            self.assertEqual(result["recommendations"], [])
            self.assertEqual(result["all_eligible_plans"], [])
            self.assertIn("allowed risk range", result["excluded_plans"][0]["reasons"][0])
            plan.update(min_risk_pct=20,max_risk_pct=20)
            result = recommend(BASE, {}, n_sims=100, plan_config=(rules,pd.DataFrame([plan])))
            self.assertEqual(result["recommendations"][0]["risk_eligibility"]["assessed_pct"],20)


if __name__ == "__main__":
    unittest.main()
