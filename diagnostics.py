"""Whitelisted, bounded diagnostic data: no review text, cookies, accounts, IPs or paths."""
import platform
import threading
from collections import deque
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

EVENTS = {"network_blocked", "network_check_failed", "browser_close_failed", "browser_action_failed",
          "unexpected_server_error", "policy_check_blocked", "startup_protected"}
OPERATIONS = {"login", "check", "select", "prepare", "publish", "discard", "resolve", "saved_check", "location", "network"}


class Diagnostics:
    def __init__(self):
        self._events = deque(maxlen=50)
        self._lock = threading.Lock()

    def record(self, code, operation=""):
        if code not in EVENTS or operation not in OPERATIONS | {""}:
            raise ValueError("Diagnostic values must be approved codes, never raw errors.")
        with self._lock:
            self._events.append({"at": datetime.now(timezone.utc).isoformat(), "code": code, "operation": operation})

    def events(self):
        with self._lock:
            return [dict(event) for event in self._events]


def diagnostic_report(cfg, browser, protection, diagnostics):
    dependencies = {}
    for package in ("flask", "playwright", "python-dotenv"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = "missing"
    network = browser.get("network", {})
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {"python": platform.python_version(), "os": platform.system(), "dependencies": dependencies},
            "setup": {"mode": cfg["mode"], "browser_channel": cfg["browser_channel"],
                      "city_geolocation": cfg["city_geolocation"], "application_proxy": False,
                      "uk_guard_enabled": cfg["network_guard"]["enabled"]},
            "browser": {"status": browser.get("status", "unknown"), "busy": bool(browser.get("busy"))},
            "network": {key: network.get(key) for key in ("enabled", "status", "allowed", "country", "address_families", "checked_at", "code")},
            "local_storage": {key: protection.get(key) for key in ("status", "method", "code", "checked_entries")},
            "events": diagnostics.events(),
            "limits": ["UK country checks sample browser traffic; they do not certify Avast, DNS or all IPv6 routes.",
                       "Use the Avast kill switch; the app is not an OS firewall.",
                       "Local permissions are not encryption and do not stop administrators or same-user malware.",
                       "Policy confirmations are self-attestations; saved reviews are not proof of public visibility."]}
