"""City/location binding tests. No external lookups, accounts, or posting."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app import create_app
from app_config import ConfigError, validate_config
from city_location import GOOGLE_ORIGINS, load_city_locations, selected_location
from review_store import validate_review

LONDON = "London, England, United Kingdom"
MANCHESTER = "Manchester, England, United Kingdom"


class CityCoordinateTests(unittest.TestCase):
    def test_all_picker_cities_have_bounded_offline_coordinates(self):
        points = load_city_locations()
        self.assertEqual(len(points), 76)
        for point in points.values():
            self.assertTrue(49 <= point["latitude"] <= 61)
            self.assertTrue(-9 <= point["longitude"] <= 3)
            self.assertTrue(point["osm_url"].startswith("https://www.openstreetmap.org/"))

    def test_bangor_wales_and_northern_ireland_are_not_mixed(self):
        points = load_city_locations()
        self.assertNotEqual(points["Bangor, Wales, United Kingdom"], points["Bangor, Northern Ireland, United Kingdom"])

    def test_invalid_auto_setting_is_rejected(self):
        with self.assertRaises(ConfigError):
            validate_config({"city_geolocation": "true"})

    def test_missing_coordinate_data_is_an_explicit_setup_error(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ConfigError):
            load_city_locations(folder)

    def test_incomplete_or_nonfinite_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "uk_cities.json").write_text(json.dumps({"England": ["London"]}), encoding="utf-8")
            path = root / "uk_city_locations.json"
            for points in ({}, {LONDON: {"latitude": float("nan"), "longitude": 0}}):
                path.write_text(json.dumps({"locations": points}), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_city_locations(root)

    def test_clear_selection_restores_manual_config_if_present(self):
        location = selected_location(validate_config({"target": {"lat": 0, "lng": 0}}), {}, revision=3)
        self.assertTrue(location["enabled"])
        self.assertEqual((location["source"], location["latitude"], location["longitude"]), ("config", 0, 0))
        self.assertEqual(location["revision"], 3)


class CityLocationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, config={"mode": "poster", "city_geolocation": True})
        self.worker = self.app.extensions["review_worker"]
        self.addCleanup(self.worker.close)
        self.client = self.app.test_client()
        self.assertEqual(self.client.post('/api/unlock', json={'token': self.app.extensions['dashboard_token']}).status_code, 200)
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}

    def select(self, city):
        return self.client.post("/api/browser/location", json={"city": city}, headers=self.headers)

    def test_selection_before_login_does_not_launch_browser_and_applies_to_launch_options(self):
        response = self.select(LONDON)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["location"]["enabled"])
        self.assertIsNone(self.worker._context)
        self.assertEqual(self.worker.snapshot()["status"], "disconnected")
        self.worker._playwright = MagicMock(devices={})
        options = self.worker.browser_launch_options()
        self.assertEqual(options["geolocation"], {key: load_city_locations()[LONDON][key] for key in ("latitude", "longitude")})
        self.assertNotIn("proxy", options)
        self.assertNotIn("permissions", options)

    def test_existing_browser_updates_without_restarting_and_limits_permission_to_google(self):
        context = MagicMock()
        self.worker._context = context
        self.worker._state_update(status="connected", email="owner@example.com")
        self.assertEqual(self.select(MANCHESTER).status_code, 200)
        point = load_city_locations()[MANCHESTER]
        context.set_geolocation.assert_called_once_with({"latitude": point["latitude"], "longitude": point["longitude"]})
        self.assertEqual({call.kwargs["origin"] for call in context.grant_permissions.call_args_list}, set(GOOGLE_ORIGINS))
        context.close.assert_not_called()
        self.assertEqual(self.worker.snapshot()["status"], "connected")

    def test_all_uk_clears_city_and_granted_permissions(self):
        context = MagicMock()
        self.worker._context = context
        self.select(LONDON)
        result = self.select("")
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json["location"]["enabled"])
        context.set_geolocation.assert_called_with(None)
        self.assertEqual(context.clear_permissions.call_count, 2)
        self.assertEqual(result.json["location"]["revision"], 2)

    def test_unknown_city_does_not_change_location_or_connection(self):
        self.worker._state_update(status="connected", email="owner@example.com")
        for city in ("Invented city", None, 7, {"latitude": 50}):
            self.assertEqual(self.select(city).status_code, 400)
        state = self.worker.snapshot()
        self.assertEqual(state["status"], "connected")
        self.assertFalse(state["location"]["enabled"])
        self.assertFalse(state["busy"])

    def test_csrf_is_required(self):
        self.assertEqual(self.client.post("/api/browser/location", json={"city": LONDON}).status_code, 403)

    def test_active_draft_blocks_location_switch(self):
        store = self.app.extensions["review_store"]
        store.create(validate_review({"target": "Market", "expected_name": "Market", "account_email": "owner@example.com",
                                      "text": "My experience", "stars": 4}))
        self.assertEqual(self.select(LONDON).status_code, 409)
        self.assertFalse(self.worker.snapshot()["location"]["enabled"])

    def test_location_failure_closes_inconsistent_browser_without_claiming_success(self):
        context = MagicMock()
        context.set_geolocation.side_effect = RuntimeError("Browser disconnected")
        self.worker._context = context
        self.worker._state_update(status="connected", email="owner@example.com")
        self.assertEqual(self.select(LONDON).status_code, 502)
        context.close.assert_called_once()
        self.assertIsNone(self.worker._context)
        state = self.worker.snapshot()
        self.assertEqual(state["status"], "disconnected")
        self.assertFalse(state["location"]["enabled"])

    def test_refresh_snapshot_preserves_selected_city(self):
        self.select(LONDON)
        self.assertEqual(self.client.get("/api/status").json["browser"]["location"]["selection"], LONDON)

    def test_extension_mode_cannot_accept_city_location_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder, config={"mode": "extension", "network_guard": {"enabled": False}})
            client = app.test_client()
            self.assertEqual(client.post('/api/unlock', json={'token': app.extensions['dashboard_token']}).status_code, 200)
            client.get("/")
            with client.session_transaction() as session:
                headers = {"X-CSRF-Token": session["csrf"]}
            self.assertEqual(client.post("/api/browser/location", json={"city": LONDON}, headers=headers).status_code, 409)
            app.extensions["review_worker"].close()


if __name__ == "__main__":
    unittest.main()
