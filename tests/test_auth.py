"""Authentication integration tests. Run: python -m unittest tests.test_auth -v"""
import http.cookiejar
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import uvicorn

from app import auth
from app.main import app
from tests.test_system import BASE


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {"AUTH_DB_PATH": os.path.join(cls.temp.name, "auth.sqlite3"), "COOKIE_SECURE": "0"})
        cls.environment.start()
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(app, log_level="critical"))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={"sockets": [cls.sock]}, daemon=True)
        cls.thread.start()
        for _ in range(200):
            if cls.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("Test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.sock.close()
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        with auth.database() as db:
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM users")
            db.execute("DELETE FROM auth_attempts")
        from app.admin import init_catalog
        with auth.database() as db:
            db.execute("DELETE FROM managed_plans")
            db.execute("DELETE FROM catalog_settings")
        init_catalog()
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, path, data=None, headers=None, method=None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            response = self.client.open(request)
        except urllib.error.HTTPError as error:
            response = error
        body = response.read().decode()
        result = json.loads(body) if body and response.headers.get("content-type", "").startswith("application/json") else body
        return response.status, result, response.headers

    def register(self, **changes):
        return self.request("/api/auth/register", {
            "name": "Sample User", "email": "sample@example.com", "password": "test-passphrase-2026", **changes,
        })

    def test_pages_and_apis_require_login(self):
        status, body, _ = self.request("/assessment")
        self.assertEqual(status, 200)
        self.assertIn('id="auth-form"', body)
        for path in ("/api/auth/me", "/api/plans", "/api/model-performance", "/api/assessments/latest"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request("/api/recommend", {"questionnaire": BASE})[0], 401)
        status, body, _ = self.request("/static/index.html")
        self.assertEqual(status, 200)
        self.assertIn('id="auth-form"', body)
        self.assertEqual(self.request("/templates/index.html")[0], 404)

    def test_register_hashes_password_and_opens_dashboard(self):
        status, data, headers = self.register(email=" Sample@Example.com ")
        self.assertEqual(status, 201)
        self.assertEqual(data["user"]["email"], "sample@example.com")
        self.assertNotIn("password_hash", data["user"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=lax", headers["Set-Cookie"])
        self.assertNotIn("Max-Age", headers["Set-Cookie"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        with auth.database() as db:
            user = db.execute("SELECT * FROM users").fetchone()
            session = db.execute("SELECT * FROM sessions").fetchone()
        self.assertNotEqual(user["password_hash"], "test-passphrase-2026")
        self.assertTrue(auth.verify_password("test-passphrase-2026", user["password_hash"]))
        self.assertNotEqual(session["token_hash"], next(iter(self.cookies)).value)
        self.assertEqual(self.request("/api/auth/me")[1]["user"]["name"], "Sample User")
        self.assertIn('id="f"', self.request("/assessment")[1])
        self.assertIn('id="first-assessment"', self.request("/login")[1])
        self.assertEqual(self.request("/api/plans")[0], 200)

    def test_duplicate_email_is_case_insensitive(self):
        self.register()
        self.assertEqual(self.register(email="SAMPLE@example.com")[0], 409)

    def test_registration_validates_fields(self):
        for changes in ({"password": "short"}, {"email": "invalid"}, {"name": "  "}):
            with self.subTest(changes=changes):
                self.assertEqual(self.register(**changes)[0], 422)

    def test_login_and_generic_invalid_credentials(self):
        self.register()
        self.cookies.clear()
        wrong = self.request("/api/auth/login", {"email": "sample@example.com", "password": "wrong"})
        unknown = self.request("/api/auth/login", {"email": "missing@example.com", "password": "wrong"})
        self.assertEqual(wrong[0], 401)
        self.assertEqual(wrong[1], unknown[1])
        status, data, _ = self.request("/api/auth/login", {"email": "SAMPLE@example.com", "password": "test-passphrase-2026"})
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["name"], "Sample User")

    def test_remember_me_sets_expiry_and_sessions_survive_initialization(self):
        _, _, headers = self.register(remember_me=True)
        self.assertIn("Max-Age=604800", headers["Set-Cookie"])
        auth.init_db()
        self.assertEqual(self.request("/api/auth/me")[0], 200)

    def test_logout_requires_csrf_and_revokes_cookie(self):
        _, data, _ = self.register()
        old_cookie = next(iter(self.cookies)).value
        self.assertEqual(self.request("/api/auth/logout", {}, method="POST")[0], 403)
        self.assertEqual(self.request("/api/auth/logout", {}, {"X-CSRF-Token": data["csrf_token"]})[0], 204)
        self.assertEqual(self.request("/api/auth/me")[0], 401)
        self.assertEqual(self.request("/api/auth/me", headers={"Cookie": f"{auth.COOKIE_NAME}={old_cookie}"})[0], 401)

    def test_expired_and_forged_sessions_are_rejected(self):
        self.register()
        with auth.database() as db:
            db.execute("UPDATE sessions SET expires_at = 0")
        self.assertEqual(self.request("/api/auth/me")[0], 401)
        self.cookies.clear()
        self.assertEqual(self.request("/api/auth/me", headers={"Cookie": f"{auth.COOKIE_NAME}=forged"})[0], 401)

    def test_cross_origin_auth_and_mutations_are_rejected(self):
        payload = {"name": "Another User", "email": "another@example.com", "password": "test-passphrase-2026"}
        self.assertEqual(self.request("/api/auth/register", payload, {"Origin": "https://another.example"})[0], 403)
        self.assertEqual(self.request("/api/auth/login", payload, {"Sec-Fetch-Site": "cross-site"})[0], 403)
        _, data, _ = self.register()
        headers = {"X-CSRF-Token": data["csrf_token"], "Origin": "https://another.example"}
        self.assertEqual(self.request("/api/auth/logout", {}, headers)[0], 403)
        self.assertEqual(self.request("/api/recommend", {"questionnaire": BASE}, headers)[0], 403)

    def test_rate_limit_blocks_repeated_attempts(self):
        with auth.database() as db:
            db.execute("INSERT INTO auth_attempts VALUES (?, 30, ?)",
                       (auth.hashlib.sha256(b"127.0.0.1").hexdigest(), int(time.time()) + 300))
        status, _, headers = self.register()
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)

    def test_recommendation_requires_csrf_and_preserves_prediction(self):
        _, data, _ = self.register()
        payload = {"questionnaire": BASE, "preferences": {"horizon_years": 1}}
        self.assertEqual(self.request("/api/recommend", payload)[0], 403)
        # Exercise the real models and simulation through the authenticated API.
        status, result, _ = self.request("/api/recommend", payload, {"X-CSRF-Token": data["csrf_token"]})
        self.assertEqual(status, 200, result)
        self.assertIn("conditions", result["risk"])
        self.assertTrue(result["recommendations"])
        self.assertEqual(result["settings"]["horizon_years"], 1)
        saved = self.request("/api/assessments/latest")[1]["assessment"]
        self.assertEqual(saved["result"], result)
        self.assertTrue(saved["completed_at"])

    def test_home_results_are_private_persistent_and_replaceable(self):
        _, account, _ = self.register()
        self.assertIsNone(self.request("/api/assessments/latest")[1]["assessment"])
        self.assertIn('id="first-assessment"', self.request("/home")[1])
        headers = {"X-CSRF-Token": account["csrf_token"]}
        payload = {"questionnaire": BASE}
        with patch("app.main.recommend", return_value={"version": 1}):
            self.assertEqual(self.request("/api/recommend", payload, headers)[0], 200)
        with patch("app.main.recommend", return_value={"version": 2}):
            self.assertEqual(self.request("/api/recommend", payload, headers)[0], 200)
        with patch("app.main.recommend", side_effect=RuntimeError("simulation failed")):
            self.assertEqual(self.request("/api/recommend", payload, headers)[0], 500)
        self.assertEqual(self.request("/api/assessments/latest")[1]["assessment"]["result"], {"version": 2})
        self.cookies.clear()
        self.register(email="another@example.com")
        self.assertIsNone(self.request("/api/assessments/latest")[1]["assessment"])
        self.cookies.clear()
        self.request("/api/auth/login", {"email": "sample@example.com", "password": "test-passphrase-2026"})
        auth.init_db()
        self.assertEqual(self.request("/api/assessments/latest")[1]["assessment"]["result"], {"version": 2})

    def test_admin_setup_creates_separate_credentials_without_elevating_users(self):
        from app.create_admin import main
        self.register()
        with patch("builtins.input", side_effect=["Local Admin","local-admin@example.com"]), patch("app.create_admin.getpass", return_value="setup-passphrase-2026"), patch("builtins.print"):
            main()
        self.assertEqual(self.request("/api/auth/admin-login", {"email":"local-admin@example.com","password":"setup-passphrase-2026"})[0], 200)
        with patch("builtins.input", side_effect=["Local Admin","sample@example.com"]), patch("app.create_admin.getpass", return_value="setup-passphrase-2026"), patch("builtins.print"), self.assertRaises(SystemExit):
            main()
        with auth.database() as db:
            self.assertEqual(db.execute("SELECT role FROM users WHERE email='sample@example.com'").fetchone()["role"], "user")

    def admin_login(self):
        with auth.database() as db:
            db.execute("INSERT INTO users (name,email,password_hash,created_at,role) VALUES (?,?,?,?,?)",
                       ("Administrator", "admin@example.com", auth.hash_password("admin-passphrase-2026"), int(time.time()), "admin"))
        self.cookies.clear()
        status, data, _ = self.request("/api/auth/admin-login", {"email": "admin@example.com", "password": "admin-passphrase-2026"})
        self.assertEqual(status, 200)
        return data

    def test_admin_role_cannot_be_registered_or_bypassed(self):
        _, data, _ = self.register(role="admin")
        self.assertEqual(data["user"]["role"], "user")
        self.assertEqual(self.request("/admin")[0], 403)
        for path in ("/api/admin/overview", "/api/admin/users"):
            self.assertEqual(self.request(path)[0], 403)
        self.assertEqual(self.request("/api/admin/rules", {}, {"X-CSRF-Token": data["csrf_token"]}, "PUT")[0], 403)
        self.assertEqual(self.request("/api/auth/admin-login", {"email":"sample@example.com","password":"test-passphrase-2026"})[0], 401)
        admin = self.admin_login()
        self.assertEqual(admin["user"]["role"], "admin")
        self.assertEqual(self.request("/api/admin/overview")[0], 200)
        self.assertIn('id="plans-panel"', self.request("/home")[1])
        self.assertEqual(self.request("/api/admin/rules", {}, method="PUT")[0], 403)

    def test_admin_catalog_validation_and_prediction_updates(self):
        admin = self.admin_login()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        overview = self.request("/api/admin/overview")[1]
        plan = next(p for p in overview["plans"] if p["plan_id"] == "P03")
        plan["base_premium_inr"] = 12345
        self.assertEqual(self.request("/api/admin/plans/P03", plan, headers, "PUT")[0], 200)
        status, result, _ = self.request("/api/recommend", {"questionnaire": BASE, "preferences":{"horizon_years":1}}, headers)
        self.assertEqual(status, 200)
        recommended = next(p for p in result["all_eligible_plans"] if p["plan_id"] == "P03")
        self.assertAlmostEqual(recommended["premium_year1"], 12345 * 1.35)
        plan["active"] = False
        self.assertEqual(self.request("/api/admin/plans/P03", plan, headers, "PUT")[0], 200)
        self.assertNotIn("P03", [p["plan_id"] for p in self.request("/api/plans")[1]])
        self.assertEqual(self.request("/api/admin/plans/P03", dict(plan, copay_pct=101), headers, "PUT")[0], 422)
        self.assertEqual(self.request("/api/admin/plans", dict(plan, plan_id="NEW"), headers)[0], 201)
        self.assertEqual(self.request("/api/admin/plans", dict(plan, plan_id="NEW"), headers)[0], 409)
        rules = overview["rules"]
        rules["smoker_premium_loading_pct"] = 25
        self.assertEqual(self.request("/api/admin/rules", rules, headers, "PUT")[0], 200)
        from app.admin import prediction_catalog
        from src.recommend import premium
        saved_rules, plans = prediction_catalog()
        p = next(plans.itertuples())
        self.assertAlmostEqual(premium(p, 45, False, True, saved_rules) / premium(p, 45, False, False, saved_rules), 1.25)
        rules["premium_age_factors"][0][1] = 34
        self.assertEqual(self.request("/api/admin/rules", rules, headers, "PUT")[0], 422)

    def test_self_password_change_revokes_sessions(self):
        _, data, _ = self.register()
        headers = {"X-CSRF-Token": data["csrf_token"]}
        profile = self.request("/api/profile")[1]
        self.assertEqual(profile["role"], "user")
        self.assertNotIn("password_hash", profile)
        self.assertEqual(self.request("/api/profile/password", {"current_password":"wrong","new_password":"changed-password"}, headers)[0], 400)
        self.assertEqual(self.request("/api/profile/password", {"current_password":"test-passphrase-2026","new_password":"changed-password"}, headers)[0], 200)
        self.assertEqual(self.request("/api/auth/me")[0], 401)
        self.assertEqual(self.request("/api/auth/login", {"email":"sample@example.com","password":"test-passphrase-2026"})[0], 401)
        self.assertEqual(self.request("/api/auth/login", {"email":"sample@example.com","password":"changed-password"})[0], 200)

    def test_admin_password_reset_and_own_password_change(self):
        _, user, _ = self.register()
        old_cookie = next(iter(self.cookies)).value
        admin = self.admin_login()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        path = f"/api/admin/users/{user['user']['id']}/password"
        self.assertEqual(self.request(path, {"admin_password":"wrong","new_password":"reset-passphrase"}, headers)[0], 400)
        self.assertEqual(self.request(path, {"admin_password":"admin-passphrase-2026","new_password":"reset-passphrase"}, headers)[0], 200)
        self.assertEqual(self.request("/api/auth/me", headers={"Cookie":f"{auth.COOKIE_NAME}={old_cookie}"})[0], 401)
        own = f"/api/admin/users/{admin['user']['id']}/password"
        self.assertEqual(self.request(own, {"admin_password":"admin-passphrase-2026","new_password":"another-password"}, headers)[0], 403)
        self.assertEqual(self.request("/api/profile/password", {"current_password":"admin-passphrase-2026","new_password":"admin-new-passphrase"}, headers)[0], 200)
        self.assertEqual(self.request("/api/auth/me")[0], 401)
        self.assertEqual(self.request("/api/auth/admin-login", {"email":"admin@example.com","password":"admin-new-passphrase"})[0], 200)
        self.cookies.clear()
        self.assertEqual(self.request("/api/auth/login", {"email":"sample@example.com","password":"reset-passphrase"})[0], 200)

    def test_plan_risk_ranges_validate_and_filter_api_results(self):
        admin = self.admin_login()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        plan = next(p for p in self.request("/api/admin/overview")[1]["plans"] if p["plan_id"] == "P03")
        self.assertEqual((plan["min_risk_pct"], plan["max_risk_pct"]), (0, 100))
        for invalid in ({"min_risk_pct": 80, "max_risk_pct": 20}, {"max_risk_pct": 101}, {"min_risk_pct": -1}, {"risk_condition": "invalid"}):
            self.assertEqual(self.request("/api/admin/plans/P03", dict(plan, **invalid), headers, "PUT")[0], 422)
        plan.update(risk_condition="diabetes", min_risk_pct=0, max_risk_pct=99)
        self.assertEqual(self.request("/api/admin/plans/P03", plan, headers, "PUT")[0], 200)
        payload = {"questionnaire": dict(BASE, diabetes="yes"), "preferences": {"horizon_years": 1}}
        status, result, _ = self.request("/api/recommend", payload, headers)
        self.assertEqual(status, 200)
        self.assertNotIn("P03", [p["plan_id"] for p in result["all_eligible_plans"]])
        self.assertNotIn("P03", [p["plan_id"] for p in result["recommendations"]])
        excluded = next(p for p in result["excluded_plans"] if p["plan_id"] == "P03")
        self.assertTrue(any("allowed risk range" in reason for reason in excluded["reasons"]))
        plan.update(min_risk_pct=100, max_risk_pct=100)
        self.assertEqual(self.request("/api/admin/plans/P03", plan, headers, "PUT")[0], 200)
        result = self.request("/api/recommend", payload, headers)[1]
        matched = next(p for p in result["all_eligible_plans"] if p["plan_id"] == "P03")
        self.assertEqual(matched["risk_eligibility"]["assessed_pct"], 100)
        self.assertTrue(matched["risk_eligibility"]["eligible"])

    def test_legacy_plans_receive_risk_defaults_without_losing_edits(self):
        from app.admin import catalog_snapshot
        with auth.database() as db:
            data = json.loads(db.execute("SELECT data FROM managed_plans WHERE plan_id='P03'").fetchone()["data"])
            for key in ("risk_condition", "min_risk_pct", "max_risk_pct"):
                data.pop(key, None)
            data["base_premium_inr"] = 4321
            db.execute("UPDATE managed_plans SET data=? WHERE plan_id='P03'", (json.dumps(data),))
        plan = next(p for p in catalog_snapshot()[1] if p["plan_id"] == "P03")
        self.assertEqual(plan["base_premium_inr"], 4321)
        self.assertEqual((plan["risk_condition"], plan["min_risk_pct"], plan["max_risk_pct"]), ("highest", 0, 100))

    def test_invalid_preferences_are_rejected(self):
        _, data, _ = self.register()
        status, _, _ = self.request("/api/recommend", {
            "questionnaire": BASE, "preferences": {"annual_budget_inr": -1},
        }, {"X-CSRF-Token": data["csrf_token"]})
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
