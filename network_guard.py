"""Sample the poster browser's UK egress; never a replacement for a VPN kill switch."""
import ipaddress
import secrets
import threading
import time
from datetime import datetime, timezone

from review_store import ReviewError

# Both requests use the actual browser, not Python/Node's potentially different VPN route.
TRACE_URLS = ("https://www.cloudflare.com/cdn-cgi/trace", "https://1.1.1.1/cdn-cgi/trace")
MAX_TRACE_LENGTH = 4096


def parse_trace(text):
    if not isinstance(text, str) or len(text) > MAX_TRACE_LENGTH:
        raise ValueError("Invalid network check response.")
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ip", "loc"}:
            if key in fields:
                raise ValueError("Ambiguous network check response.")
            fields[key] = value.strip()
    address = ipaddress.ip_address(fields.get("ip", ""))
    country = fields.get("loc", "")
    if not address.is_global or len(country) != 2 or not country.isascii() or not country.isupper() or not country.isalpha():
        raise ValueError("Network check did not identify a public IP and country.")
    return country, address.version


class UKNetworkGuard:
    def __init__(self, cfg, clock=time.monotonic):
        self.enabled = cfg["enabled"]
        self.interval = cfg["interval_seconds"]
        self.timeout_ms = cfg["timeout_ms"]
        self._clock = clock
        self._lock = threading.Lock()
        self._verified_at = None
        self._state = {"enabled": self.enabled, "status": "unchecked" if self.enabled else "disabled",
                       "country": "", "address_families": [], "checked_at": "",
                       "code": "not_checked" if self.enabled else "disabled",
                       "message": "UK IP must be checked in the poster browser." if self.enabled else "UK-IP protection is disabled."}

    def snapshot(self):
        with self._lock:
            result = {**self._state, "address_families": list(self._state["address_families"])}
            fresh = self._verified_at is not None and self._clock() - self._verified_at < self.interval
        result["allowed"] = not self.enabled or (result["status"] == "verified" and fresh)
        if self.enabled and result["status"] == "verified" and not fresh:
            result.update(status="stale", code="check_expired", message="UK-IP check expired; a fresh check is required.")
        return result

    def invalidate(self):
        with self._lock:
            self._verified_at = None

    def check(self, context, force=False):
        if not self.enabled or (not force and self.snapshot()["allowed"]):
            return self.snapshot()
        country, families, code = "", set(), "check_unavailable"
        page = None
        try:
            page = context.new_page()
            # No Google cookies or review text are sent to these fixed HTTPS origins.
            for endpoint in TRACE_URLS:
                url = endpoint + "?tasmee_check=" + secrets.token_hex(8)
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                if response is None or response.status != 200 or page.url != url:
                    raise ValueError("Network check was redirected or unavailable.")
                if "text/plain" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Unexpected network check content.")
                text = page.evaluate("() => (document.body?.innerText || '').slice(0, 4097)")
                country, family = parse_trace(text)
                families.add(family)
                if country != "GB":
                    code = "not_uk"
                    raise ValueError("The sampled browser IP is not in the UK.")
            with self._lock:
                self._verified_at = self._clock()
                self._state.update(status="verified", country="GB", address_families=sorted(families),
                                   checked_at=datetime.now(timezone.utc).isoformat(), code="uk_verified",
                                   message="UK browser IP confirmed at the last check. Avast kill switch is still required.")
            return self.snapshot()
        except Exception as error:
            message = ("Posting blocked: the browser IP is not UK. Connect Avast to a UK server and check again."
                       if code == "not_uk" else
                       "Posting blocked: UK IP could not be confirmed. Check Avast/internet and retry; no fallback is allowed.")
            with self._lock:
                self._verified_at = None
                self._state.update(status="blocked", country=country, address_families=sorted(families),
                                   checked_at=datetime.now(timezone.utc).isoformat(), code=code, message=message)
            # External responses/exceptions may contain IPs, URLs or browser-profile paths.
            raise ReviewError(message, 409) from None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
