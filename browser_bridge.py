"""Use the person's ordinary Chrome session through a narrowly scoped extension."""
import os
import shutil
import subprocess
import threading
import secrets
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from review_store import ReviewError, business_location, maps_url, normalize_name, valid_email
from poster import business_key
from personal_browser import browser_kind


def open_normal_chrome(url):
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    executable = next((str(path) for path in candidates if path.is_file()), None) or shutil.which("google-chrome") or shutil.which("chromium")
    if executable:
        subprocess.Popen([executable, "--new-tab", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif not webbrowser.open(url):
        raise ReviewError("Open Chrome and visit Google Maps to sign in.")


class BrowserBridge:
    extension_mode = True

    def __init__(self, store):
        self.store = store
        self.browser_kind = browser_kind()
        self.browser_label = "Firefox" if self.browser_kind == "firefox" else "Chrome"
        self._lock = threading.Lock()
        self.expected_email = ""
        self.verification = None
        self.state = {"status": "disconnected", "email": "", "busy": False, "transport": "extension",
                      "browser_kind": self.browser_kind,
                      "message": f"Sign in in {self.browser_label}, then check connection. Load the Tasmee extension in that same browser."}

    def snapshot(self):
        with self._lock:
            self._expire_verification()
            return dict(self.state)

    def _expire_verification(self):
        if self.verification and self.verification["expires"] < time.monotonic():
            self.verification = None
            self.state["busy"] = False

    def reserve_check(self, review_id):
        with self._lock:
            self._expire_verification()
            review = self.store.get(review_id)
            if self.state["busy"] or self.store.active() or self.state["status"] != "connected":
                raise ReviewError("Saved-review checks need an idle connected browser.", 409)
            if self.state["email"] != review["account_email"]:
                raise ReviewError("Switch to this review's Google account before checking it.", 409)
            token = secrets.token_urlsafe(32)
            self.verification = {"id": review_id, "token": token, "expires": time.monotonic() + 120}
            self.state["busy"] = True
            return token

    def check_reservation(self, review_id, token):
        with self._lock:
            self._expire_verification()
            if (not self.verification or self.verification["id"] != review_id or not isinstance(token, str)
                    or not secrets.compare_digest(token, self.verification["token"])):
                raise ReviewError("Saved-review check expired. Try again when the browser is idle.", 409)

    def release_check(self):
        with self._lock:
            self.verification = None
            self.state["busy"] = False

    def command(self, action, value=None):
        with self._lock:
            self._expire_verification()
            if self.state["busy"]:
                raise ReviewError("Finish the current action first.", 409)
            if action in {"login", "select"}:
                self.expected_email = value
                self.state.update(status="signing_in", email="", message=f"Finish Google sign-in in {self.browser_label}, then Check connection.")
            elif action == "check":
                return
            elif action == "prepare":
                self.store.transition(value, "queued", "preparing", f"Checking your {self.browser_label} session and business.")
                self.state["busy"] = True
            elif action == "publish":
                self.state["busy"] = True
            elif action == "discard":
                self.state["busy"] = False
        if action == "login" and self.browser_kind == "chrome":
            open_normal_chrome("https://accounts.google.com/ServiceLogin?" + urlencode({
                "continue": "https://www.google.com/maps?hl=en", "hl": "en", "Email": value,
            }))

    def connect(self, assertion):
        if self.browser_kind == "firefox" and assertion.get("browser_kind") != "firefox":
            raise ReviewError("Open the dashboard in the dedicated Firefox profile, not personal Chrome.", 409)
        email = assertion.get("email", "")
        if not valid_email(email):
            raise ReviewError(f"Google account was not detected. Finish sign-in in {self.browser_label}, then try again.")
        email = email.strip().lower()
        if self.expected_email and email != self.expected_email:
            raise ReviewError(f"{self.browser_label} is signed into a different Google account. Switch accounts in Google Maps.", 409)
        with self._lock:
            self.state.update(status="connected", email=email, busy=False,
                              message=f"Google account verified in {self.browser_label}. Your browser manages the saved session; VPN protection is not verified by this app.")
        self.store.remember_account(email)

    def validate_assertion(self, review_id, assertion):
        review = self.store.get(review_id)
        if (not isinstance(assertion, dict) or not isinstance(assertion.get("email"), str)
                or assertion["email"].lower() != review["account_email"]
                or not isinstance(assertion.get("name"), str)
                or normalize_name(assertion["name"]) != normalize_name(review["expected_name"])
                or assertion.get("text") != review["text"]
                or type(assertion.get("stars")) is not int or assertion["stars"] != review["stars"]):
            raise ReviewError("The verified account, business, text or rating does not match the draft.", 409)
        url = assertion.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ReviewError("The extension did not verify a Google Maps business URL.")
        url = maps_url(url)
        parsed = urlsplit(url)
        if parsed.hostname not in {"www.google.com", "google.com", "maps.google.com", "www.google.co.uk", "www.google.com.pk"} or not parsed.path.startswith("/maps"):
            raise ReviewError("A resolved Google Maps business page is required.")
        key = business_key(url, assertion["name"])
        if review["business_key"] and key != review["business_key"]:
            raise ReviewError("The business changed after preview. Nothing was submitted.", 409)
        if self.store.duplicate(review_id, key, review["account_email"]):
            raise ReviewError("This account already has a confirmed or uncertain review for this business. Check Google Maps first.", 409)
        return {"business_name": assertion["name"], "business_url": url, "business_key": key,
                **business_location(url, assertion.get("address", ""))}

    def finish(self):
        with self._lock:
            self.state["busy"] = False

    def cancel(self, review_id):
        review = self.store.get(review_id)
        self.store.transition(review_id, review["status"], "cancelled", "Cancelled. Nothing was submitted.")
        self.finish()

    def close(self):
        pass
