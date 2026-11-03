"""Private dashboard capability, fixed expiry and non-disclosing public routes."""
import unittest
from pathlib import Path

from flask import Flask, jsonify, session

from dashboard_auth import SESSION_SECONDS, install_dashboard_auth, private_dashboard_url

ROOT = Path(__file__).resolve().parents[1]


class DashboardAuthTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.app = self.make_app()
        self.client = self.app.test_client()

    def make_app(self):
        app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        app.config.update(SECRET_KEY="fixture-key-shared-between-test-apps", TRUSTED_HOSTS=["localhost", "127.0.0.1"],
                          MAX_CONTENT_LENGTH=24000)
        install_dashboard_auth(app, clock=lambda: self.now)

        @app.get("/")
        def index():
            session.setdefault("csrf", "fixture-existing-csrf")
            return jsonify(private=True, csrf=session["csrf"])

        @app.get("/api/status")
        def status():
            return jsonify(email="private@example.com")

        @app.post("/api/browser/check")
        def browser_check():
            return jsonify(ok=True)

        @app.get("/extension/download")
        def download():
            return "private download"

        return app

    def unlock(self, client=None, **kwargs):
        return (client or self.client).post("/api/unlock", json={"token": self.app.extensions["dashboard_token"]}, **kwargs)

    def test_independent_local_client_cannot_read_or_control_existing_session(self):
        self.assertEqual(self.unlock().status_code, 200)
        outsider = self.app.test_client()
        for path in ("/api/status", "/api/history", "/api/diagnostics?download=1", "/extension/download"):
            self.assertEqual(outsider.get(path).status_code, 401)
        self.assertEqual(outsider.post("/api/browser/check", json={}).status_code, 401)
        locked = outsider.get("/")
        self.assertEqual(locked.status_code, 200)
        self.assertIn("unlockForm", locked.text)
        self.assertNotIn("private@example.com", locked.text)
        with outsider.session_transaction() as state:
            self.assertNotIn("csrf", state)

    def test_health_is_public_but_contains_no_state_or_capability(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.json, {"ok": True, "application": "tasmee-personal-reviews", "authentication_required": True})
        self.assertNotIn(self.app.extensions["dashboard_token"], self.client.get("/").text)
        response = self.client.get("/static/unlock.js")
        try:
            self.assertEqual(response.status_code, 200)
        finally:
            response.close()

    def test_missing_wrong_nonascii_or_nonobject_code_never_unlocks(self):
        for data in ({}, {"token": "wrong"}, {"token": "ä"}, {"token": 1}, {"token": "x" * 129}, []):
            self.assertEqual(self.client.post("/api/unlock", json=data).status_code, 403)
            self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_query_parameter_does_not_unlock_or_reflect_private_code(self):
        token = self.app.extensions["dashboard_token"]
        response = self.client.get("/?unlock=" + token)
        self.assertNotIn(token, response.text)
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_origin_content_type_remote_address_and_host_checks(self):
        for origin in ("https://localhost", "http://localhost:4444", "http://evil.example", "null"):
            self.assertEqual(self.unlock(headers={"Origin": origin}).status_code, 403)
        self.assertEqual(self.client.post("/api/unlock", data="token=bad").status_code, 415)
        self.assertEqual(self.unlock(environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
        self.assertEqual(self.client.get("/", environ_overrides={"REMOTE_ADDR": "192.0.2.1"}).status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "evil.example"}).status_code, 400)
        self.assertEqual(self.unlock(headers={"Origin": "http://localhost"}).status_code, 200)

    def test_unlock_rotates_session_and_issues_httponly_strict_cookie(self):
        with self.client.session_transaction() as state:
            state["csrf"] = "old-known-value"
            state["other"] = "old-state"
        response = self.unlock()
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(response.json, {"ok": True})
        with self.client.session_transaction() as state:
            self.assertNotEqual(state["csrf"], "old-known-value")
            self.assertNotIn("other", state)
        self.assertEqual(self.client.get("/api/status").json["email"], "private@example.com")

    def test_access_expires_after_fixed_eight_hours_despite_activity(self):
        self.unlock()
        self.now += SESSION_SECONDS - 1
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/status").status_code, 200)
        self.now += 1
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.post("/api/browser/check", json={}).status_code, 401)
        with self.client.session_transaction() as state:
            self.assertNotIn("csrf", state)

    def test_restart_rejects_previous_cookie_even_with_same_flask_secret(self):
        self.unlock()
        cookie = self.client.get_cookie("session")
        restarted = self.make_app().test_client()
        restarted.set_cookie("session", cookie.value)
        self.assertEqual(restarted.get("/api/status").status_code, 401)

    def test_private_url_uses_fragment_and_rejects_external_or_query_targets(self):
        url = private_dashboard_url(self.app, "http://127.0.0.1:5000/")
        self.assertEqual(url, "http://127.0.0.1:5000/#unlock=" + self.app.extensions["dashboard_token"])
        self.assertNotIn("?", url)
        for base in ("https://evil.example", "http://localhost:5000/?token=x", "http://localhost:5000/#x", "http://user@localhost:5000/"):
            with self.assertRaises(ValueError):
                private_dashboard_url(self.app, base)


if __name__ == "__main__":
    unittest.main()
