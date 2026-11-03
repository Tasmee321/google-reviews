"""Bounded client-reported UK samples; the extension enforces the actual probes.

An unlocked dashboard and the installed extension are trusted peers. This is not
remote attestation, an OS firewall, or independent proof of every network route.
"""
import re
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timezone

from diagnostics import Diagnostics
from review_store import ReviewError


class ExtensionNetwork:
    NETWORK_AGE = 30
    NETWORK_POLICY = "uk-browser-egress-v1"
    MINIMUM_EXTENSION = (1, 0, 7)

    def init_network(self):
        self.diagnostics = Diagnostics()
        self._network_challenges = OrderedDict()
        self._network_deadline = 0
        self._extension_version = ""
        self._network = self._network_state("unknown", "not_checked")

    @staticmethod
    def _network_state(status, code, country="", **details):
        messages = {
            "verified": "UK browser IP verified. Same city is not required.",
            "blocked": "UK-IP check blocked. Connect Avast to the UK, then check again.",
            "unknown": "UK IP not verified. Check UK IP with signed extension 1.0.7 or later.",
        }
        return {"enabled": True, "allowed": status == "verified", "status": status,
                "country": country, "code": code, "checked_at": "", "expires_at": "",
                "address_families": [], "policy": ExtensionNetwork.NETWORK_POLICY,
                "max_age_seconds": 30, "message": messages[status], **details}

    def network_snapshot(self):
        with self._lock:
            if self._network["allowed"] and time.monotonic() >= self._network_deadline:
                self._network = self._network_state("unknown", "stale")
            return {**self._network, "address_families": list(self._network["address_families"])}

    def require_network(self):
        # Explicit OFF is retained for legacy API fixtures / poster configuration.
        # The signed extension itself never offers a guard-disable command.
        if self.cfg.get("network_guard", {}).get("enabled", True) and not self.network_snapshot()["allowed"]:
            raise ReviewError(self._network["message"], 409)

    def network_challenge(self):
        with self._lock:
            now = time.monotonic()
            self._network_challenges = OrderedDict((key, end) for key, end in self._network_challenges.items() if end > now)
            while len(self._network_challenges) >= 8:
                self._network_challenges.popitem(last=False)
            challenge = secrets.token_urlsafe(32)
            self._network_challenges[challenge] = now + self.NETWORK_AGE
            return challenge

    def invalidate_network(self):
        with self._lock:
            self._network_deadline = 0
            self._network = self._network_state("unknown", "check_failed")
            self.diagnostics.record("network_check_failed", "network")
            return self.network_snapshot()

    def accept_network(self, data):
        with self._lock:
            challenge = data.get("challenge")
            if (not isinstance(challenge, str) or len(challenge) > 100
                    or self._network_challenges.pop(challenge, 0) <= time.monotonic()):
                self.invalidate_network()
                raise ReviewError("UK-IP check expired. Click Check UK IP again.", 409)
            self._network_deadline = 0
            self._network = self._network_state("unknown", "check_failed")
            extension, sample = data.get("extension"), data.get("network")
            if not isinstance(extension, dict) or not isinstance(sample, dict):
                raise ReviewError("Update the signed extension to 1.0.7 or later, then refresh.", 409)
            version = extension.get("version", "")
            match = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})", version) if isinstance(version, str) else None
            capabilities = extension.get("capabilities")
            if (not match or tuple(map(int, match.groups())) < self.MINIMUM_EXTENSION
                    or not isinstance(capabilities, list) or "uk_network_guard" not in capabilities
                    or extension.get("browser_kind") != self.browser_kind
                    or sample.get("enabled") is not True or sample.get("policy") != self.NETWORK_POLICY):
                raise ReviewError("Use the matching browser with Tasmee extension 1.0.7 or later and UK-IP protection.", 409)
            self._extension_version = version
            country = sample.get("country", "")
            country = country if isinstance(country, str) and re.fullmatch(r"[A-Z]{2}", country) else ""
            if sample.get("status") != "verified" or sample.get("allowed") is not True or country != "GB":
                self._network = self._network_state("blocked", "network_blocked", country)
                self.diagnostics.record("network_blocked", "network")
                return self.network_snapshot()
            try:
                checked = datetime.fromisoformat(sample["checked_at"].replace("Z", "+00:00"))
                expires = datetime.fromisoformat(sample["expires_at"].replace("Z", "+00:00"))
                if checked.tzinfo is None or expires.tzinfo is None:
                    raise ValueError("timezone")
                now = datetime.now(timezone.utc)
                age = (now - checked).total_seconds()
                remaining = (expires - now).total_seconds()
                lifetime = (expires - checked).total_seconds()
                families = sample["address_families"]
                if (not -2 <= age < self.NETWORK_AGE or not 0 < remaining <= self.NETWORK_AGE + 2
                        or not 0 < lifetime <= self.NETWORK_AGE
                        or not isinstance(families, list) or not 1 <= len(families) <= 2
                        or any(type(value) is not int or value not in {4, 6} for value in families)
                        or len(set(families)) != len(families)):
                    raise ValueError("expired or malformed")
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise ReviewError("The browser UK-IP sample is stale or invalid. Check UK IP again.", 409) from None
            self._network_deadline = time.monotonic() + min(remaining, self.NETWORK_AGE - max(age, 0))
            self._network = self._network_state("verified", "uk_verified", "GB",
                checked_at=checked.isoformat(), expires_at=expires.isoformat(), address_families=sorted(families))
            return self.network_snapshot()
