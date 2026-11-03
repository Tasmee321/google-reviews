"""Startup health-check tests without opening a browser or changing live state."""
import io
import json
import socket
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from check_localhost import check_dashboard


class LocalhostLauncherTests(unittest.TestCase):
    def check(self, data=None, error=None):
        opener = MagicMock()
        if error:
            opener.open.side_effect = error
        else:
            response = opener.open.return_value.__enter__.return_value
            response.read.return_value = json.dumps(data).encode()
        with patch("check_localhost.build_opener", return_value=opener), redirect_stdout(io.StringIO()) as output:
            result = check_dashboard(5000)
        opener.open.assert_called_once_with("http://127.0.0.1:5000/api/health", timeout=3)
        if not error:
            response.read.assert_called_once_with(4096)
        return result, output.getvalue()

    def test_existing_dashboard_is_reused_without_disclosing_account(self):
        result, text = self.check({"ok": True, "application": "tasmee-personal-reviews",
                                  "authentication_required": True, "unexpected": "private@example.com"})
        self.assertEqual(result, 0)
        self.assertIn("already running", text)
        self.assertNotIn("private@example.com", text)

    def test_connection_refused_allows_normal_start(self):
        result, _ = self.check(error=URLError(ConnectionRefusedError()))
        self.assertEqual(result, 1)

    def test_unrelated_service_stops_startup(self):
        for data in ({"ok": True}, [], {"ok": False, "browser": {}, "reviews": []},
                     {"ok": True, "application": "another-service", "authentication_required": True},
                     {"ok": True, "application": "tasmee-personal-reviews", "authentication_required": False},
                     {"ok": True, "application": "tasmee-personal-reviews", "authentication_required": 1}):
            self.assertEqual(self.check(data)[0], 2)

    def test_http_error_stops_startup(self):
        self.assertEqual(self.check(error=HTTPError("http://127.0.0.1:5000/api/health", 404, "Not found", {}, None))[0], 2)

    def test_timeout_does_not_start_a_duplicate(self):
        self.assertEqual(self.check(error=URLError(socket.timeout()))[0], 2)


if __name__ == "__main__":
    unittest.main()
