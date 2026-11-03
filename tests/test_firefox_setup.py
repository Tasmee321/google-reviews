"""Isolated launch/build/API tests; no accounts, VPN changes or live reviews."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import create_app
from build_firefox_extension import firefox_archive, firefox_sources
from personal_browser import browser_kind, open_firefox_dashboard
from review_store import ReviewError


class FirefoxSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_ordinary_profile_launch_has_no_debugger_or_spoofing(self):
        profile = Path(self.temp.name) / "firefox-profile"
        with patch("personal_browser.PROFILE", profile), patch("personal_browser.firefox_executable", return_value="firefox.exe"), patch("personal_browser.subprocess.Popen") as launch:
            open_firefox_dashboard("http://127.0.0.1:5000/")
            open_firefox_dashboard("http://127.0.0.1:5000/")
        args = launch.call_args.args[0]
        self.assertEqual(args, ["firefox.exe", "--no-remote", "--profile", str(profile), "--new-window", "http://127.0.0.1:5000/"])
        self.assertEqual(launch.call_args_list[0], launch.call_args_list[1])
        self.assertTrue(profile.is_dir())
        self.assertFalse((profile / "user.js").exists())

    def test_launch_rejects_external_destinations_and_credentials(self):
        with patch("personal_browser.subprocess.Popen") as launch:
            for url in ("https://accounts.google.com/", "http://evil.example/", "http://user@localhost/", "http://127.0.0.1:5000/api/status"):
                with self.assertRaises(ReviewError):
                    open_firefox_dashboard(url)
        launch.assert_not_called()

    def test_browser_setting_is_allowlisted(self):
        with patch.dict(os.environ, {"REVIEW_BROWSER": "firefox"}):
            self.assertEqual(browser_kind(), "firefox")
        with patch.dict(os.environ, {"REVIEW_BROWSER": "camoufox"}):
            with self.assertRaises(ReviewError):
                browser_kind()

    def test_firefox_manifest_and_promise_namespace(self):
        sources = firefox_sources()
        manifest = json.loads(sources["manifest.json"])
        self.assertEqual(manifest["background"], {"scripts": ["background.js"]})
        settings = manifest["browser_specific_settings"]["gecko"]
        self.assertEqual(settings["strict_min_version"], "142.0")
        self.assertNotIn("none", settings["data_collection_permissions"]["required"])
        self.assertIn("personallyIdentifyingInfo", settings["data_collection_permissions"]["required"])
        self.assertEqual(manifest["permissions"], ["storage"])
        self.assertTrue(all("<all_urls>" != host for host in manifest["host_permissions"]))
        for name, source in sources.items():
            if name.endswith(".js"):
                self.assertNotIn(b"chrome.", source)
                self.assertIn(b"browser.", source)

    def test_unsigned_archive_contains_only_source_files(self):
        with zipfile.ZipFile(firefox_archive()) as archive:
            self.assertEqual(set(archive.namelist()), set(firefox_sources()))
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("PRIVACY.md", archive.namelist())
            self.assertFalse(any(".env" in name or "cookies" in name or "sqlite" in name for name in archive.namelist()))

    def firefox_app(self):
        with patch.dict(os.environ, {"REVIEW_BROWSER": "firefox"}):
            app = create_app(Path(self.temp.name) / "data", config={"mode": "extension"})
        client = app.test_client()
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

    def test_setup_discloses_unsigned_install_and_unverified_vpn(self):
        _, client, _ = self.firefox_app()
        page = client.get("/").get_data(as_text=True)
        self.assertIn("DEDICATED FIREFOX", page)
        self.assertIn("about:addons", page)
        self.assertIn("signed add-on permanent", page)
        self.assertIn("VPN protection is not verified", page)
        self.assertNotIn("chrome://extensions", page)
        download = client.get("/extension/firefox/download")
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
            self.assertIn("manifest.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
