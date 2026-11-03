"""Poster configuration/API regressions; no external accounts or posting."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import create_app
from app_config import ConfigError, load_config, validate_config
from browser_options import launch_options
from poster import ReviewWorker
from review_store import ReviewStore, ReviewError, validate_review

ROOT = Path(__file__).resolve().parents[1]
EMAIL = "owner@example.com"
PAYLOAD = {"target": "https://www.google.com/maps/place/Market/data=!1sfixture",
           "expected_name": "Market", "account_email": EMAIL, "stars": 4,
           "text": "My own experience."}


class ConfigurationTests(unittest.TestCase):
    def test_ready_defaults_are_extension_with_sandboxed_optional_poster(self):
        cfg = validate_config({})
        options = launch_options(cfg, {})
        self.assertEqual(cfg["mode"], "extension")
        self.assertTrue(options["chromium_sandbox"])
        self.assertFalse(cfg["city_geolocation"])
        self.assertTrue(cfg["network_guard"]["enabled"])
        self.assertEqual(options["locale"], "en-GB")
        self.assertEqual(options["timezone_id"], "Europe/London")
        for absent in ("proxy", "user_agent", "geolocation", "permissions"):
            self.assertNotIn(absent, options)
        self.assertEqual(cfg, load_config(ROOT / "config.example.json", environ={}))

    def test_invalid_config_is_rejected_before_browser_start(self):
        invalid = [[], {"mode": "unknown"}, {"port": True}, {"port": 65536},
                   {"browser_channel": "firefox"}, {"proxies": ["http://secret@proxy:80"]},
                   {"delay_range": [2, 1]}, {"delay_range": [0, float("nan")]},
                   {"target": {"lat": 1}}, {"target": {"lat": 91, "lng": 0}},
                   {"timeouts": {"element_ms": 0}}, {"timeot": 100}]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ConfigError):
                validate_config(values)

    def test_json_errors_are_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"mode":', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path, environ={})

    def test_environment_overrides_and_missing_file_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            cfg = load_config(path, environ={"REVIEW_MODE": "extension", "PORT": "5055", "BROWSER_CHANNEL": "msedge"})
            self.assertEqual((cfg["mode"], cfg["port"], cfg["browser_channel"]), ("extension", 5055, "msedge"))
            with self.assertRaises(ConfigError):
                load_config(path, environ={"PORT": "invalid"})

    def test_device_options_merge_once_and_zero_coordinates_are_valid(self):
        cfg = validate_config({"device": "Pixel 5", "target": {"lat": 0, "lng": 0}, "browser_channel": "chromium"})
        descriptor = {"viewport": {"width": 393, "height": 851}, "user_agent": "device-fixture", "default_browser_type": "chromium", "chromium_sandbox": False}
        options = launch_options(cfg, {"Pixel 5": descriptor})
        self.assertEqual(options["viewport"], descriptor["viewport"])
        self.assertEqual(options["geolocation"], {"latitude": 0, "longitude": 0})
        self.assertNotIn("default_browser_type", options)
        self.assertNotIn("channel", options)
        self.assertIn("default_browser_type", descriptor)
        self.assertTrue(options["chromium_sandbox"])

    def test_unknown_device_has_an_actionable_error(self):
        with self.assertRaises(ReviewError):
            launch_options(validate_config({"device": "not-a-device"}), {})

    def test_city_list_covers_all_four_nations_and_disambiguates_bangor(self):
        cities = json.loads((ROOT / "uk_cities.json").read_text(encoding="utf-8"))
        self.assertEqual({nation: len(names) for nation, names in cities.items()},
                         {"England": 55, "Scotland": 8, "Wales": 7, "Northern Ireland": 6})
        self.assertIn("Bangor", cities["Wales"])
        self.assertIn("Bangor", cities["Northern Ireland"])
        for names in cities.values():
            self.assertEqual(len(names), len(set(names)))

    def test_setup_check_skips_browser_without_creating_a_profile(self):
        from check_setup import main
        with patch("playwright.sync_api.sync_playwright") as launcher:
            self.assertEqual(main(["--skip-browser"]), 0)
        launcher.assert_not_called()


class FixtureWorker(ReviewWorker):
    def _new_page(self):
        page = MagicMock()
        page.url = PAYLOAD["target"]
        return page

    def _navigate_business(self, page, url, email):
        self.last_navigation = (url, email)

    def _resolve(self, request):
        self.last_resolution = request
        return {"name": "Market", "email": request[1], "url": PAYLOAD["target"],
                "address": "Manchester, UK", "latitude": None, "longitude": None}

    def _check(self, unused):
        self.store.remember_account(self._expected_email or EMAIL)
        self._state_update(status="connected", email=self._expected_email or EMAIL)


class PosterSandboxTests(unittest.TestCase):
    def test_installed_chrome_starts_without_no_sandbox_switch(self):
        from check_setup import installed_browser
        from playwright.sync_api import sync_playwright
        if not installed_browser("chrome", ""):
            self.skipTest("Installed Chrome is needed for the optional poster sandbox smoke test.")
        with tempfile.TemporaryDirectory() as profile, sync_playwright() as playwright:
            options = launch_options(validate_config({"mode": "poster"}), playwright.devices)
            self.assertTrue(options["chromium_sandbox"])
            options.update(headless=True, timeout=20000)
            context = playwright.chromium.launch_persistent_context(profile, **options)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                # Chrome's local version page exposes launch switches without
                # requiring an extra --enable-automation test-only switch.
                page.goto("chrome://version/")
                arguments = page.locator("#command_line").inner_text().split()
                self.assertNotIn("--no-sandbox", arguments)
                self.assertNotIn("--disable-setuid-sandbox", arguments)
            finally:
                context.close()


class PosterApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, FixtureWorker, config={"mode": "poster", "network_guard": {"enabled": False}})
        self.worker = self.app.extensions["review_worker"]
        self.addCleanup(self.worker.close)
        self.store = self.app.extensions["review_store"]
        self.client = self.app.test_client()
        self.assertEqual(self.client.post('/api/unlock', json={'token': self.app.extensions['dashboard_token']}).status_code, 200)
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}
        self.worker._state_update(status="connected", email=EMAIL)
        self.store.remember_account(EMAIL)

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def saved_draft(self):
        review = self.store.create(validate_review(PAYLOAD))
        self.store.update(review["id"], status="unconfirmed", business_key="place:fixture", business_url=PAYLOAD["target"])
        return self.store.get(review["id"])

    def test_explicit_poster_factory_does_not_launch_a_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder, config={"mode": "poster"})
            worker = app.extensions["review_worker"]
            self.assertIsInstance(worker, ReviewWorker)
            self.assertIsNone(worker._thread)
            self.assertEqual(worker.snapshot()["transport"], "poster")
            worker.close()

    def test_old_one_argument_factory_remains_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder, lambda store: FixtureWorker(store), config={})
            app.extensions["review_worker"].close()

    def test_factory_internal_type_error_is_not_retried(self):
        def broken(store, cfg):
            raise TypeError("factory internal error")
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(TypeError, "factory internal"):
            create_app(folder, broken, config={})

    def test_poster_page_has_uk_city_picker_and_no_extension_requirement(self):
        page = self.client.get("/").text
        self.assertIn("POSTER MODE", page)
        self.assertIn("no extension required", page)
        self.assertIn("Bangor, Wales, United Kingdom", page)
        self.assertIn("Bangor, Northern Ireland, United Kingdom", page)
        self.assertIn("Avast SecureLine VPN", page)

    def test_resolution_uses_worker_not_extension_and_does_not_create_review(self):
        response = self.post("/api/business/resolve", {"target": "Market, Manchester, England, United Kingdom"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["assertion"]["name"], "Market")
        self.assertEqual(self.store.count(), 0)
        self.assertFalse(self.worker.snapshot()["busy"])

    def test_poster_rejects_browser_extension_assertions(self):
        self.assertEqual(self.post("/api/browser/verified", {"email": EMAIL}).status_code, 409)

    def test_saved_check_returns_completed_result_without_extension(self):
        review = self.saved_draft()
        with patch("poster_pages.saved_review", return_value="saved-123"):
            response = self.post(f"/api/reviews/{review['id']}/check-start", {"confirmation_token": review["confirmation_token"]})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["completed"])
        self.assertEqual(response.json["review"]["status"], "posted")
        self.assertFalse(self.worker.snapshot()["busy"])
        self.assertEqual(self.worker.last_navigation[1], EMAIL)

    def test_saved_check_wrong_account_or_bad_token_does_not_inspect(self):
        review = self.saved_draft()
        path = f"/api/reviews/{review['id']}/check-start"
        self.assertEqual(self.post(path, {"confirmation_token": "bad"}).status_code, 409)
        self.worker._state_update(email="other@example.com")
        with patch("poster_pages.saved_review") as inspect:
            self.assertEqual(self.post(path, {"confirmation_token": review["confirmation_token"]}).status_code, 409)
        inspect.assert_not_called()
        self.assertFalse(self.worker.snapshot()["busy"])

    def test_saved_check_failure_does_not_claim_success_or_leave_busy(self):
        review = self.saved_draft()
        with patch("poster_pages.saved_review", side_effect=ReviewError("No matching own review.", 409)):
            response = self.post(f"/api/reviews/{review['id']}/check-start", {"confirmation_token": review["confirmation_token"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.get(review["id"])["status"], "unconfirmed")
        self.assertFalse(self.worker.snapshot()["busy"])

    def test_account_navigation_uses_verified_numeric_index(self):
        self.worker._account_indexes[EMAIL] = "2"
        url = self.worker._account_url(PAYLOAD["target"] + "?authuser=0", EMAIL)
        self.assertIn("authuser=2", url)
        self.assertIn("gl=gb", url)
        self.assertEqual(self.worker._account_url("https://maps.app.goo.gl/fixture", EMAIL), "https://maps.app.goo.gl/fixture")

    def test_shutdown_rejects_new_commands(self):
        self.worker.close()
        with self.assertRaises(ReviewError):
            self.worker.command("check")


if __name__ == "__main__":
    unittest.main()
