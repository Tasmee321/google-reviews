"""Isolated launch/build/API tests; no accounts, VPN changes or live reviews."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import create_app
from build_firefox_extension import firefox_archive, firefox_sources, source_archive
from personal_browser import browser_kind, open_firefox_dashboard
from review_store import ReviewError


class FirefoxSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_ordinary_profile_launch_has_no_debugger_or_spoofing(self):
        profile = Path(self.temp.name) / "firefox-profile"
        profile.mkdir()
        session_marker = profile / "cookies.sqlite"
        addon_marker = profile / "extensions.json"
        session_marker.write_bytes(b"existing-test-session")
        addon_marker.write_bytes(b"existing-signed-addon-test-marker")
        with patch("personal_browser.PROFILE", profile), patch("personal_browser.firefox_executable", return_value="firefox.exe"), patch("personal_browser.subprocess.Popen") as launch:
            open_firefox_dashboard("http://127.0.0.1:5000/")
            open_firefox_dashboard("http://127.0.0.1:5000/")
        args = launch.call_args.args[0]
        self.assertEqual(args, ["firefox.exe", "--no-remote", "--profile", str(profile), "--new-window", "http://127.0.0.1:5000/"])
        self.assertEqual(launch.call_args_list[0], launch.call_args_list[1])
        self.assertTrue(profile.is_dir())
        self.assertFalse((profile / "user.js").exists())
        self.assertEqual(session_marker.read_bytes(), b"existing-test-session")
        self.assertEqual(addon_marker.read_bytes(), b"existing-signed-addon-test-marker")

    def test_default_factory_selects_firefox_without_launching_it(self):
        with patch.dict(os.environ, {}, clear=True), patch("personal_browser.subprocess.Popen") as launch:
            app = create_app(Path(self.temp.name) / "default-data", config={})
        worker = app.extensions["review_worker"]
        self.addCleanup(worker.close)
        self.assertEqual(worker.snapshot()["transport"], "extension")
        self.assertEqual(worker.snapshot()["browser_kind"], "firefox")
        launch.assert_not_called()

    def test_offline_setup_does_not_claim_extension_guard_can_be_disabled(self):
        from app_config import validate_config
        from check_setup import main
        cfg = validate_config({"mode": "extension", "network_guard": {"enabled": False}})
        output = io.StringIO()
        with patch("app_config.load_config", return_value=cfg), patch("sys.stdout", output):
            self.assertEqual(main(["--skip-browser"]), 0)
        self.assertIn("UK-IP guard: enabled", output.getvalue())
        self.assertIn("always enabled", output.getvalue())
        self.assertNotIn("DISABLED", output.getvalue())

    def test_launch_rejects_external_destinations_and_credentials(self):
        with patch("personal_browser.subprocess.Popen") as launch:
            for url in ("https://accounts.google.com/", "http://evil.example/", "http://user@localhost/", "http://127.0.0.1:5000/api/status"):
                with self.assertRaises(ReviewError):
                    open_firefox_dashboard(url)
        launch.assert_not_called()

    def test_browser_setting_is_allowlisted(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(browser_kind(), "firefox")
        with patch.dict(os.environ, {"REVIEW_BROWSER": "firefox"}):
            self.assertEqual(browser_kind(), "firefox")
        with patch.dict(os.environ, {"REVIEW_BROWSER": "camoufox"}):
            with self.assertRaises(ReviewError):
                browser_kind()

    def test_firefox_manifest_and_promise_namespace(self):
        sources = firefox_sources()
        manifest = json.loads(sources["manifest.json"])
        self.assertEqual(manifest["version"], "1.0.8")
        self.assertEqual(manifest["background"], {"scripts": ["network_guard.js", "background.js"]})
        settings = manifest["browser_specific_settings"]["gecko"]
        self.assertEqual(settings["id"], "tasmee-personal-reviews@local.invalid")
        self.assertEqual(settings["strict_min_version"], "142.0")
        self.assertNotIn("none", settings["data_collection_permissions"]["required"])
        self.assertIn("personallyIdentifyingInfo", settings["data_collection_permissions"]["required"])
        self.assertIn("locationInfo", settings["data_collection_permissions"]["required"])
        self.assertEqual(manifest["permissions"], ["storage"])
        self.assertTrue(all("<all_urls>" != host for host in manifest["host_permissions"]))
        self.assertIn("https://www.cloudflare.com/*", manifest["host_permissions"])
        self.assertIn("https://1.1.1.1/*", manifest["host_permissions"])
        for name, source in sources.items():
            if name.endswith(".js"):
                self.assertNotIn(b"chrome.", source)
        self.assertIn(b"browser.", sources["background.js"])
        self.assertIn(b"TasmeeNetworkGuard", sources["network_guard.js"])

    def test_unsigned_archive_contains_only_source_files(self):
        with zipfile.ZipFile(firefox_archive()) as archive:
            self.assertEqual(set(archive.namelist()), set(firefox_sources()))
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("PRIVACY.md", archive.namelist())
            self.assertFalse(any(".env" in name or "cookies" in name or "sqlite" in name for name in archive.namelist()))

    def test_archives_are_deterministic_with_fixed_file_metadata(self):
        for builder in (firefox_archive, source_archive):
            self.assertEqual(builder().getvalue(), builder().getvalue())
            with zipfile.ZipFile(builder()) as archive:
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                for entry in archive.infolist():
                    self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(entry.external_attr >> 16, 0o100644)

    def test_source_archive_rebuilds_without_dependencies_or_private_files(self):
        folder = Path(self.temp.name) / "source"
        folder.mkdir()
        with zipfile.ZipFile(source_archive()) as archive:
            names = archive.namelist()
            self.assertIn("chrome_extension/network_guard.js", names)
            self.assertTrue(all(name.startswith("chrome_extension/") or name in {
                "build_firefox_extension.py", "EXTENSION_PRIVACY.md", "FIREFOX_SOURCE_BUILD.md"} for name in names))
            archive.extractall(folder)
        result = subprocess.run([sys.executable, "-I", "-S", "build_firefox_extension.py"], cwd=folder,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((folder / "dist/tasmee-firefox-1.0.8-unsigned.xpi").read_bytes(), firefox_archive().getvalue())
        self.assertEqual((folder / "dist/tasmee-firefox-1.0.8-source.zip").read_bytes(), source_archive().getvalue())

    def firefox_app(self):
        with patch.dict(os.environ, {"REVIEW_BROWSER": "firefox"}):
            app = create_app(Path(self.temp.name) / "data", config={"mode": "extension", "network_guard": {"enabled": False}})
        client = app.test_client()
        self.assertEqual(client.post('/api/unlock', json={'token': app.extensions['dashboard_token']}).status_code, 200)
        client.get("/")
        with client.session_transaction() as session:
            headers = {"X-CSRF-Token": session["csrf"]}
        return app, client, headers

    def test_firefox_connection_rejects_chrome_or_missing_browser_kind(self):
        app, client, headers = self.firefox_app()
        for kind in ("chrome", None):
            response = client.post("/api/browser/verified", json={"email": "owner@example.com", "browser_kind": kind}, headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(app.extensions["review_worker"].snapshot()["status"], "disconnected")
        self.assertEqual(client.post("/api/browser/verified", json={"email": "owner@example.com", "browser_kind": "firefox"}, headers=headers).status_code, 200)

    def test_firefox_login_never_opens_personal_chrome(self):
        _, client, headers = self.firefox_app()
        with patch("browser_bridge.open_normal_chrome") as chrome:
            response = client.post("/api/browser/login", json={"email": "owner@example.com"}, headers=headers)
        chrome.assert_not_called()
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json["requires_extension"])

    def test_setup_discloses_unsigned_install_and_browser_country_check(self):
        _, client, _ = self.firefox_app()
        page = client.get("/").get_data(as_text=True)
        self.assertIn("DEDICATED FIREFOX", page)
        self.assertIn("about:addons", page)
        self.assertIn("signed add-on permanent", page)
        self.assertIn("Check UK IP", page)
        self.assertNotIn("chrome://extensions", page)
        download = client.get("/extension/firefox/download")
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
            self.assertIn("manifest.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
