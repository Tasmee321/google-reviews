import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from app import acquire_runtime_lock, create_app
from review_store import ReviewError, ReviewStore, business_location, maps_url, validate_review


def payload(**changes):
    return {"target": "https://www.google.com/maps/place/My+Market", "expected_name": "My Market",
            "text": "I visited today. The staff were helpful.", "stars": 4,
            "account_email": "owner@example.com", **changes}


class ValidationTests(unittest.TestCase):
    def test_whole_rating_required(self):
        for stars in (0, 6, -1, True, 4.5, "5", None):
            with self.subTest(stars=stars), self.assertRaises(ReviewError):
                validate_review(payload(stars=stars))

    def test_all_ratings_and_exact_text(self):
        for stars in range(1, 6):
            data = validate_review(payload(stars=stars, text="Good & clear.\n{My own words} <3"))
            self.assertEqual(data["stars"], stars)
            self.assertEqual(data["text"], "Good & clear.\n{My own words} <3")

    def test_missing_fields_and_limits(self):
        for change in ({"text": "   "}, {"text": "x" * 4001}, {"expected_name": []}, {"account_email": "not an email"}):
            with self.subTest(change=change), self.assertRaises(ReviewError):
                validate_review(payload(**change))

    def test_unsafe_urls_rejected(self):
        for target in ("http://www.google.com/maps", "https://evil.example/maps", "https://google.com.evil.example/maps",
                       "file:///etc/passwd", "javascript:alert(1)", "https://user:pass@www.google.com/maps",
                       "https://www.google.com:8080/maps", "https://www.google.com/login", "//localhost/maps",
                       "https://goo.gl/other", "https://www.google.com:bad/maps"):
            with self.subTest(target=target), self.assertRaises(ReviewError):
                validate_review(payload(target=target))

    def test_search_is_encoded(self):
        url = maps_url("Market A&B #Karachi")
        self.assertIn("Market%20A%26B%20%23Karachi", url)

    def test_maps_share_link_supported(self):
        self.assertEqual(maps_url("https://maps.app.goo.gl/example"), "https://maps.app.goo.gl/example")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ReviewStore(self.directory.name)

    def test_location_upgrade_preserves_existing_history_and_is_repeatable(self):
        from contextlib import closing
        from pathlib import Path
        import sqlite3
        directory = Path(self.directory.name) / "legacy"
        directory.mkdir()
        with closing(sqlite3.connect(directory / "reviews.sqlite3")) as db, db:
            db.execute("""CREATE TABLE reviews (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                target TEXT NOT NULL, navigation_url TEXT NOT NULL, expected_name TEXT NOT NULL,
                account_email TEXT NOT NULL, stars INTEGER NOT NULL, text TEXT NOT NULL,
                status TEXT NOT NULL, message TEXT NOT NULL, business_name TEXT NOT NULL DEFAULT '',
                business_url TEXT NOT NULL DEFAULT '', business_key TEXT NOT NULL DEFAULT '',
                confirmation_token TEXT NOT NULL, events TEXT NOT NULL DEFAULT '[]')""")
            db.execute("""INSERT INTO reviews
                (id, created_at, updated_at, target, navigation_url, expected_name,
                 account_email, stars, text, status, message, confirmation_token)
                VALUES ('legacy', 'now', 'now', 'Market', 'https://www.google.com/maps',
                        'Market', 'owner@example.com', 4, 'Existing review', 'posted', 'Saved', 'token')""")
        for _ in range(2):
            migrated = ReviewStore(directory).get("legacy")
            self.assertEqual(migrated["text"], "Existing review")
            self.assertEqual(migrated["status"], "posted")
            self.assertEqual(migrated["business_address"], "")
            self.assertIsNone(migrated["business_latitude"])
            self.assertIsNone(migrated["business_longitude"])


    def test_second_process_cannot_recover_active_reviews(self):
        from pathlib import Path
        handle = acquire_runtime_lock(Path(self.directory.name))
        try:
            with self.assertRaises(RuntimeError):
                acquire_runtime_lock(Path(self.directory.name))
        finally:
            handle.close()

    def test_uncertain_worker_failure_is_recorded_without_retry(self):
        from poster import ReviewWorker
        import time
        class FailingWorker(ReviewWorker):
            calls = 0
            def _publish(self, review_id):
                self.calls += 1
                self.store.transition(review_id, "publishing", "submitting", "Sent once")
                raise OSError("Connection lost after click")
        review = self.store.create(validate_review(payload()))
        self.store.update(review["id"], status="publishing", business_key="place:123")
        worker = FailingWorker(self.store)
        try:
            worker.command("publish", review["id"])
            deadline = time.monotonic() + 2
            while worker.snapshot()["busy"] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(worker.calls, 1)
            self.assertEqual(self.store.get(review["id"])["status"], "unconfirmed")
        finally:
            worker.close()

    def test_one_active_review_under_concurrency(self):
        barrier = threading.Barrier(5)
        def create():
            barrier.wait()
            try:
                return self.store.create(validate_review(payload()))["id"]
            except ReviewError:
                return None
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: create(), range(5)))
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_publish_transition_is_atomic(self):
        review = self.store.create(validate_review(payload()))
        self.store.update(review["id"], status="ready")
        self.store.transition(review["id"], "ready", "publishing", "Checked")
        with self.assertRaises(ReviewError):
            self.store.transition(review["id"], "ready", "publishing", "Repeated")

    def test_restart_never_resumes_submission(self):
        review = self.store.create(validate_review(payload()))
        self.store.update(review["id"], status="submitting")
        self.store.recover()
        self.assertEqual(self.store.get(review["id"])["status"], "unconfirmed")
        self.assertIsNone(self.store.active())

    def test_restart_invalidates_unsubmitted_preview(self):
        review = self.store.create(validate_review(payload()))
        self.store.update(review["id"], status="ready")
        self.store.recover()
        self.assertEqual(self.store.get(review["id"])["status"], "interrupted")

    def test_uncertain_and_confirmed_reviews_block_duplicates(self):
        review = self.store.create(validate_review(payload()))
        for status in ("posted", "unconfirmed", "submitting"):
            self.store.update(review["id"], status=status, business_key="place:123")
            self.assertTrue(self.store.duplicate("new", "place:123", "owner@example.com"))
            self.assertFalse(self.store.duplicate("new", "place:123", "other@example.com"))
            self.assertFalse(self.store.duplicate("new", "place:456", "owner@example.com"))


class BusinessLocationTests(unittest.TestCase):
    def test_place_coordinates_not_camera_center(self):
        url = "https://www.google.com/maps/place/Market/@40,50,17z/data=!8m2!3d24.8607!4d67.0011!16splace"
        info = business_location(url, "  Main Road,\n Karachi  ")
        self.assertEqual(info["business_address"], "Main Road, Karachi")
        self.assertEqual(info["business_latitude"], 24.8607)
        self.assertEqual(info["business_longitude"], 67.0011)

    def test_missing_ambiguous_or_invalid_coordinates_are_not_guessed(self):
        for suffix in ("@24,67,17z", "data=!3d91!4d67", "data=!3d24!4d181",
                       "data=!3d24!4d67!3d25!4d68", "data=!3d24!4d67extra"):
            with self.subTest(suffix=suffix):
                info = business_location("https://www.google.com/maps/place/Market/" + suffix)
                self.assertIsNone(info["business_latitude"])
                self.assertIsNone(info["business_longitude"])

    def test_zero_negative_and_encoded_place_coordinates(self):
        for coordinates in ("!3d0!4d0", "%213d-33.9%214d18.4"):
            info = business_location("https://www.google.com/maps/place/Market/data=" + coordinates)
            self.assertIsNotNone(info["business_latitude"])

    def test_untrusted_links_and_bad_address_types(self):
        self.assertIsNone(business_location("https://evil.example/maps/data=!3d24!4d67")["business_latitude"])
        for address in (None, [], "x" * 501):
            with self.assertRaises(ReviewError):
                business_location("https://www.google.com/maps", address)


class FakeWorker:
    def __init__(self, store):
        self.actions = []
    def snapshot(self):
        return {"status": "connected", "email": "owner@example.com", "busy": False, "message": "Connected"}
    def command(self, action, value=None):
        self.actions.append((action, value))
    def cancel(self, review_id):
        self.actions.append(("cancel", review_id))
    def close(self):
        pass


class ConnectionErrorTests(unittest.TestCase):
    def setUp(self):
        from poster import ReviewWorker
        from unittest.mock import MagicMock
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.worker = ReviewWorker(ReviewStore(self.directory.name))
        self.page = MagicMock()
        self.worker._new_page = lambda: self.page
        self.worker._consent = MagicMock()

    def test_missing_sign_in_has_specific_guidance(self):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        self.page.locator.return_value.first.wait_for.side_effect = BrowserTimeout("No account label")
        with self.assertRaisesRegex(ReviewError, "sign-in was not detected"):
            self.worker._check(None)
        self.page.close.assert_called_once()

    def test_network_timeout_is_distinct_from_missing_login(self):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        self.page.goto.side_effect = BrowserTimeout("Network timeout")
        with self.assertRaisesRegex(ReviewError, "Maps took too long"):
            self.worker._check(None)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(self.directory.name, FakeWorker)
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.token = session["csrf"]
        self.headers = {"X-CSRF-Token": self.token, "Origin": "http://localhost"}

    def test_csrf_and_cross_origin_requests_rejected(self):
        self.assertEqual(self.client.post("/api/reviews", json=payload()).status_code, 403)
        self.assertEqual(self.client.post("/api/reviews", json=payload(), headers={**self.headers, "Origin": "https://evil.example"}).status_code, 403)

    def test_non_local_clients_and_invalid_hosts_rejected(self):
        self.assertEqual(self.client.get("/api/status", environ_overrides={"REMOTE_ADDR": "10.0.0.2"}).status_code, 403)
        self.assertEqual(self.client.get("/api/status", headers={"Host": "evil.example"}).status_code, 400)

    def test_non_object_json_and_wrong_account_rejected(self):
        self.assertEqual(self.client.post("/api/reviews", json=[], headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post("/api/reviews", json=payload(account_email="other@example.com"), headers=self.headers).status_code, 409)

    def test_preview_does_not_publish_and_repeated_clicks_blocked(self):
        response = self.client.post("/api/reviews", json=payload(), headers=self.headers)
        self.assertEqual(response.status_code, 202)
        review = response.json["review"]
        worker = self.app.extensions["review_worker"]
        self.assertEqual(worker.actions, [("prepare", review["id"])])
        path = f"/api/reviews/{review['id']}/publish"
        token = {"confirmation_token": review["confirmation_token"]}
        self.assertEqual(self.client.post(path, json=token, headers=self.headers).status_code, 409)
        self.app.extensions["review_store"].update(review["id"], status="ready")
        self.assertEqual(self.client.post(path, json={"confirmation_token": "wrong"}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(path, json=token, headers=self.headers).status_code, 202)
        self.assertEqual(self.client.post(path, json=token, headers=self.headers).status_code, 409)
        self.assertEqual(sum(action == "publish" for action, _ in worker.actions), 1)

    def test_security_headers_and_no_legacy_password_endpoints(self):
        response = self.client.get("/")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/api/accounts").status_code, 404)
        self.assertNotIn('id="acctPass"', response.text)


if __name__ == "__main__":
    unittest.main()
