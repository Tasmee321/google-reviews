"""UK extension protocol fixtures only; never contacts Google or a real VPN."""
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app


class ExtensionNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict("os.environ", {"REVIEW_BROWSER": "firefox"}):
            self.app = create_app(self.temp.name, config={"mode": "extension"})
        self.worker = self.app.extensions["review_worker"]
        self.client = self.app.test_client()
        self.client.post("/api/unlock", json={"token": self.app.extensions["dashboard_token"]})
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def sample(self):
        now = datetime.now(timezone.utc)
        return {"challenge": self.post("/api/browser/network", {}).json["challenge"],
                "extension": {"version": "1.0.7", "browser_kind": "firefox", "capabilities": ["uk_network_guard"]},
                "network": {"enabled": True, "policy": "uk-browser-egress-v1", "status": "verified",
                            "allowed": True, "country": "GB", "address_families": [4, 6],
                            "checked_at": now.isoformat(), "expires_at": (now + timedelta(seconds=30)).isoformat()}}

    def accept(self, data=None):
        return self.post("/api/browser/network-result", data or self.sample())

    def test_default_blocks_before_login_and_never_launches_unguarded_chrome(self):
        with patch("browser_bridge.open_normal_chrome") as launch:
            self.assertEqual(self.post("/api/browser/login", {"email": "owner@example.com"}).status_code, 409)
            self.assertEqual(self.worker.snapshot()["status"], "disconnected")
            self.assertEqual(self.accept().status_code, 200)
            response = self.post("/api/browser/login", {"email": "owner@example.com"})
            self.assertEqual(response.status_code, 202)
            self.assertTrue(response.json["requires_extension"])
            launch.assert_not_called()

    def test_challenge_is_one_use_and_unknown_challenge_fails_closed(self):
        sample = self.sample()
        self.assertTrue(self.accept(sample).json["network"]["allowed"])
        self.assertEqual(self.accept(sample).status_code, 409)
        self.assertFalse(self.worker.snapshot()["network"]["allowed"])
        sample = self.sample()
        sample["challenge"] = "unknown"
        self.assertEqual(self.accept(sample).status_code, 409)

    def test_challenges_are_bounded_and_expire(self):
        for _ in range(12):
            self.sample()
        self.assertLessEqual(len(self.worker._network_challenges), 8)
        sample = self.sample()
        self.worker._network_challenges[sample["challenge"]] = time.monotonic() - 1
        self.assertEqual(self.accept(sample).status_code, 409)

    def test_old_wrong_browser_and_missing_capability_are_rejected(self):
        for changes in ({"version": "1.0.6"}, {"version": "garbage"}, {"version": None},
                        {"capabilities": "uk_network_guard"}, {"capabilities": []}, {"browser_kind": "chrome"}):
            sample = self.sample()
            sample["extension"].update(changes)
            self.assertEqual(self.accept(sample).status_code, 409)
            self.assertFalse(self.worker.snapshot()["network"]["allowed"])

    def test_failed_unknown_or_non_uk_samples_do_not_allow_actions(self):
        for changes in ({"country": "PK"}, {"country": "UK"}, {"country": ""}, {"country": ["GB"]},
                        {"allowed": "true"}, {"status": "unknown"}, {"status": "blocked"}):
            sample = self.sample()
            sample["network"].update(changes)
            response = self.accept(sample)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["network"]["allowed"])
            self.assertEqual(self.post("/api/browser/check", {}).status_code, 409)

    def test_wrong_policy_and_disabled_guard_are_rejected(self):
        for changes in ({"enabled": False}, {"enabled": 1}, {"policy": "old"}):
            sample = self.sample()
            sample["network"].update(changes)
            self.assertEqual(self.accept(sample).status_code, 409)

    def test_malformed_future_and_stale_times_fail_closed(self):
        now = datetime.now(timezone.utc)
        for changes in ({"checked_at": None}, {"checked_at": now.replace(tzinfo=None).isoformat()},
                        {"checked_at": (now + timedelta(seconds=10)).isoformat()},
                        {"checked_at": (now - timedelta(seconds=31)).isoformat()},
                        {"expires_at": (now - timedelta(seconds=1)).isoformat()},
                        {"expires_at": (now + timedelta(seconds=60)).isoformat()},
                        {"address_families": [True]}, {"address_families": [4, 4]},
                        {"address_families": []}, {"address_families": [4, 6, 8]}):
            sample = self.sample()
            sample["network"].update(changes)
            self.assertEqual(self.accept(sample).status_code, 409, changes)

    def test_local_monotonic_expiry_and_failure_invalidate_verified_sample(self):
        self.accept()
        self.worker._network_deadline = time.monotonic() - .1
        self.assertFalse(self.worker.snapshot()["network"]["allowed"])
        self.assertEqual(self.post("/api/browser/check", {}).status_code, 409)
        self.accept()
        self.assertFalse(self.post("/api/browser/network-failure", {}).json["network"]["allowed"])
        self.assertEqual(self.post("/api/browser/check", {}).status_code, 409)

    def test_only_allowlisted_report_fields_are_retained(self):
        sample = self.sample()
        sample["network"].update(ip="8.8.8.8", email="private@example.com", message="cookie-and-secret-path")
        response = self.accept(sample)
        self.assertTrue(response.json["network"]["allowed"])
        diagnostics = self.client.get("/api/diagnostics").text
        for value in ("8.8.8.8", "private@example.com", "cookie-and-secret-path", sample["challenge"]):
            self.assertNotIn(value, response.text + diagnostics)
        self.assertEqual(self.worker.diagnostics.events()[-1]["code"], "startup_protected")

    def test_reporting_requires_unlock_and_csrf_and_valid_object(self):
        self.assertEqual(self.client.post("/api/browser/network-result", json=self.sample()).status_code, 403)
        other = self.app.test_client()
        self.assertEqual(other.post("/api/browser/network", json={}).status_code, 401)
        self.assertEqual(self.post("/api/browser/network-result", []).status_code, 400)

    def test_new_worker_starts_unknown_and_does_not_persist_samples(self):
        self.accept()
        with tempfile.TemporaryDirectory() as directory:
            fresh = create_app(directory, config={"mode": "extension"})
            self.assertFalse(fresh.extensions["review_worker"].snapshot()["network"]["allowed"])

    def test_network_failure_does_not_rewrite_submission_outcome(self):
        self.accept()
        self.worker.state.update(status="connected", email="owner@example.com")
        from review_store import validate_review
        review = self.app.extensions["review_store"].create(validate_review({
            "target": "Market", "expected_name": "Market", "account_email": "owner@example.com", "stars": 4, "text": "My visit."}))
        self.app.extensions["review_store"].update(review["id"], status="submitting")
        self.worker.operation = {"id": review["id"], "expires": time.monotonic() + 30}
        self.post("/api/browser/network-failure", {})
        response = self.post(f"/api/reviews/{review['id']}/result", {"confirmation_token": review["confirmation_token"], "confirmed": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.app.extensions["review_store"].get(review["id"])["status"], "posted")


if __name__ == "__main__":
    unittest.main()
