# poster.py
# ----------------------------------------------------------------------
#  Google‑Maps review automation – with location spoofing, IP‑proxying
#  and device‑fingerprinting.
#
#  The file is a drop‑in replacement for the original poster.py.
#  It expects a `config.json` file in the same directory with the
#  following structure:
#
#  {
#      "api_key": "YOUR_GOOGLE_MAPS_API_KEY",
#      "target": {
#          "name": "My Business",
#          "lat": 31.5204,
#          "lng": 74.3587,
#          "timezone": "Asia/Karachi"
#      },
#      "proxies": [
#          "http://proxy1.example.com:3128",
#          "http://proxy2.example.com:3128"
#      ],
#      "delay_range": [2.0, 6.0]
#  }
#
#  The code below automatically picks a random proxy, random user‑agent,
#  emulates a Pixel‑5 device, forces the browser to report the target
#  latitude/longitude, and inserts small random delays so Google treats
#  each request as coming from a real human.
# ----------------------------------------------------------------------


import os
import queue
import re
import threading
import time
import json
import random
import requests

from urllib.parse import parse_qs, urlencode, urlsplit

from review_store import MAP_HOSTS, ReviewError, business_location, normalize_name


# ----------------------------------------------------------------------
# Helper – generates a key for a business from its URL / name
# ----------------------------------------------------------------------
def business_key(url, name):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ("query_place_id", "place_id", "cid", "ftid"):
        if query.get(key):
            return key + ":" + query[key][0]
    match = re.search(r"!1s([^!/?]+)", parsed.path)
    if match:
        return "place:" + match.group(1)
    return normalize_name(name) + "|" + parsed.path.rstrip("/")


# ----------------------------------------------------------------------
# Main worker – handles a single browser session
# ----------------------------------------------------------------------
class ReviewWorker:
    def __init__(self, store, cfg):
        """
        :param store:   ReviewStore instance
        :param cfg:     configuration dictionary from config.json
        """
        self.store = store
        self.cfg = cfg

        self._lock = threading.Lock()
        self._state = {"status": "disconnected", "email": "", "busy": False,
                       "message": "Connect your Google account to get started."}
        self._queue = queue.Queue()
        self._thread = None
        self._stop = threading.Event()
        self._cancel = set()
        self._playwright = None
        self._context = None
        self._prepared = {}
        self._expected_email = ""

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def _state_update(self, **values):
        with self._lock:
            self._state.update(values)

    # ------------------------------------------------------------------
    # Public API – queue a command
    # ------------------------------------------------------------------
    def command(self, action, value=None):
        with self._lock:
            if self._state["busy"]:
                raise ReviewError("The browser is busy. Wait for the current action.", 409)
            self._state["busy"] = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="personal-review-browser",
                                                daemon=True)
                self._thread.start()
        self._queue.put((action, value))

    def cancel(self, review_id):
        with self._lock:
            self._cancel.add(review_id)

    def close(self):
        self._stop.set()
        if self._thread:
            self._queue.put(("close", None))
            self._thread.join(timeout=2)

    # ------------------------------------------------------------------
    # Main worker loop
    # ------------------------------------------------------------------
    def _run(self):
        try:
            while not self._stop.is_set():
                action, value = self._queue.get()
                if action == "close":
                    break
                try:
                    getattr(self, "_" + action)(value)
                except Exception as error:
                    if isinstance(error, ReviewError):
                        message = str(error)
                    elif action in {"login", "check"}:
                        message = ("Google connection could not be checked. "
                                   "Open Google sign‑in, complete it in the browser, then check again.")
                    else:
                        message = ("Browser action failed. Check the browser window and prepare again.")
                    if action in {"prepare", "publish"}:
                        review = self.store.get(value)
                        status = ("unconfirmed" if review["status"] == "submitting"
                                  else "failed")
                        if status == "unconfirmed":
                            message = ("Submission may have reached Google. "
                                       "Check your contributions before posting again.")
                        self.store.update(value, status=status, message=message)
                        self._prepared.pop(value, None)
                    else:
                        self._state_update(status="error", message=message)
                finally:
                    self._state_update(busy=False)
        finally:
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
            if self._playwright:
                self._playwright.stop()

    # ------------------------------------------------------------------
    # Browser helper – ensures a Playwright context with proxy & spoofing
    # ------------------------------------------------------------------
    def _ensure_browser(self):
        # Re‑use existing context if still alive
        if self._context:
            try:
                self._context.cookies()
                return
            except Exception:
                self._context = None
                self._prepared.clear()

        # Start Playwright if needed
        if self._playwright is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()

        channel = os.getenv("BROWSER_CHANNEL", "chrome")
        if channel not in {"chrome", "msedge", "chromium"}:
            raise ReviewError("BROWSER_CHANNEL must be chrome, msedge or chromium.")

        # ------------------------------------------------------------------
        # Pick a random proxy from the config
        # ------------------------------------------------------------------
        proxy_url = random.choice(self.cfg.get("proxies", []))
        proxy = {"server": proxy_url} if proxy_url else None

        # ------------------------------------------------------------------
        # Pick a random User‑Agent
        # ------------------------------------------------------------------
        ua = random.choice([
            # Realistic UA strings – extend as desired
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
            "Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 12; Pixel 5 Build/QP1A.190711.020; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/111.0.5563.65 "
            "Mobile Safari/537.36"
        ])

        # ------------------------------------------------------------------
        # Device emulation – Pixel 5
        # ------------------------------------------------------------------
        from playwright.sync_api import devices
        device = devices["Pixel 5"]

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.store.directory / "browser"),
                channel=channel,
                headless=False,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
                proxy=proxy,
                user_agent=ua,
                **device
            )
            self._context.set_default_timeout(10000)

            # ------------------------------------------------------------------
            # Force the browser to report the target geolocation
            # ------------------------------------------------------------------
            target = self.cfg.get("target", {})
            if target.get("lat") and target.get("lng"):
                self._context.set_geolocation({
                    "latitude": target["lat"],
                    "longitude": target["lng"]
                })
                self._context.set_permissions(["geolocation"])

            # ------------------------------------------------------------------
            # Optional sanity check – does the proxy IP report the expected country?
            # ------------------------------------------------------------------
            try:
                r = requests.get("https://ipinfo.io/json", timeout=5)
                ip_info = r.json()
                # Example: check that the country is Pakistan or India
                if ip_info.get("country") not in {"PK", "IN"}:
                    print(f"⚠️ Proxy IP {ip_info['ip']} reports country {ip_info.get('country')}")
            except Exception:
                pass

        except Exception as error:
            raise ReviewError(
                "Cannot open the browser. Install Chrome, or set BROWSER_CHANNEL=msedge. "
                "Close other copies of this tool."
            ) from error

    # ------------------------------------------------------------------
    # Open a new page inside the context
    # ------------------------------------------------------------------
    def _new_page(self):
        self._ensure_browser()
        return self._context.new_page()

    # ------------------------------------------------------------------
    # Helper – wait for exactly one visible element
    # ------------------------------------------------------------------
    @staticmethod
    def _one_visible(locator):
        visible = [locator.nth(i) for i in range(locator.count())
                   if locator.nth(i).is_visible()]
        if len(visible) != 1:
            raise ReviewError("Google's page is ambiguous or has changed. "
                               "Continue manually in Google Maps.")
        return visible[0]

    # ------------------------------------------------------------------
    # Helper – extract email address from the account menu
    # ------------------------------------------------------------------
    @staticmethod
    def _account(page):
        labels = page.locator(
            '[aria-label*="Google Account"], [aria-label*="Google account"]'
        ).evaluate_all(
            "elements => elements.filter(e => e.getClientRects().length).map("
            "e => e.getAttribute('aria-label'))"
        )
        emails = {
            email.lower()
            for label in labels
            for email in re.findall(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}", label or "")
        }
        if len(emails) != 1:
            raise ReviewError(
                "Google account could not be verified. Finish sign-in, then click "
                "Check connection."
            )
        return emails.pop()

    # ------------------------------------------------------------------
    # Helper – verify we are on a Maps business page
    # ------------------------------------------------------------------
    @staticmethod
    def _check_google_page(page):
        parsed = urlsplit(page.url)
        if parsed.hostname not in MAP_HOSTS or not parsed.path.startswith("/maps"):
            raise ReviewError(
                "The link did not open a Google Maps business. Check the target or "
                "sign in first."
            )
        signals = page.get_by_text(
            re.compile(
                r"unusual traffic|verify you.re not a robot|browser or app may not be secure",
                re.I,
            )
        )
        if any(signals.nth(i).is_visible() for i in range(signals.count())):
            raise ReviewError(
                "Google needs your attention. Complete its security check in the browser."
            )

    # ------------------------------------------------------------------
    # Helper – accept the cookies banner if present
    # ------------------------------------------------------------------
    def _consent(self, page):
        buttons = page.get_by_role("button", name="Accept all", exact=True)
        visible = [buttons.nth(i) for i in range(buttons.count())
                   if buttons.nth(i).is_visible()]
        if len(visible) == 1:
            visible[0].click()

    # ------------------------------------------------------------------
    # Helper – login to Google
    # ------------------------------------------------------------------
    def _login(self, email):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        self._expected_email = email
        page = self._new_page()
        try:
            page.goto(
                "https://accounts.google.com/ServiceLogin?" + urlencode(
                    {
                        "continue": "https://www.google.com/maps",
                        "hl": "en",
                        "Email": email,
                    }
                ),
                wait_until="domcontentloaded",
                timeout=45000,
            )
        except BrowserTimeout as error:
            raise ReviewError(
                "Google sign‑in took too long to load. Check the browser window and your "
                "internet connection."
            ) from error
        page.bring_to_front()
        self._state_update(
            status="signing_in",
            email="",
            message=("Enter your password and complete 2FA in Google's window, "
                     "then click Check connection."),
        )

    # ------------------------------------------------------------------
    # Helper – check if we’re connected to Google
    # ------------------------------------------------------------------
    def _check(self, unused):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        page = self._new_page()
        try:
            page.goto("https://www.google.com/maps?hl=en",
                      wait_until="domcontentloaded",
                      timeout=45000)
            self._consent(page)
            try:
                page.locator(
                    '[aria-label*="Google Account"], [aria-label*="Google account"]'
                ).first.wait_for(
                    state="visible", timeout=15000
                )
            except BrowserTimeout as error:
                raise ReviewError(
                    "Google sign‑in was not detected. Enter your email and click Open "
                    "Google sign‑in, finish password/2FA in Google's window, then "
                    "Check connection."
                ) from error
            email = self._account(page)
            if self._expected_email and email != self._expected_email:
                raise ReviewError(
                    "The browser is signed into a different account. Switch accounts "
                    "in Google Maps."
                )
            self._state_update(
                status="connected",
                email=email,
                message="Google account verified. Your session is saved on this computer.",
            )
        except BrowserTimeout as error:
            raise ReviewError(
                "Google Maps took too long to load. Check your internet connection and try again."
            ) from error
        finally:
            page.close()

    # ------------------------------------------------------------------
    # Helper – cancel a review if requested
    # ------------------------------------------------------------------
    def _checkpoint(self, review_id):
        with self._lock:
            cancelled = review_id in self._cancel
            self._cancel.discard(review_id)
        if cancelled or self._stop.is_set():
            self.store.update(
                review_id,
                status="cancelled",
                message="Review cancelled. Nothing was submitted.",
            )
            self._prepared.pop(review_id, None)
            return False
        return True

    # ------------------------------------------------------------------
    # Prepare a review – open business page, fill the form
    # ------------------------------------------------------------------
    def _prepare(self, review_id):
        if not self._checkpoint(review_id):
            return
        self.store.transition(
            review_id,
            "queued",
            "preparing",
            "Opening the business and verifying your Google account.",
        )
        review = self.store.get(review_id)
        page = self._new_page()
        page.goto(
            review["navigation_url"],
            wait_until="domcontentloaded",
            timeout=45000,
        )
        self._consent(page)
        self._random_delay()  # human‑like pause after consent
        page.get_by_role("heading", level=1).first.wait_for(
            state="visible", timeout=20000
        )
        self._check_google_page(page)
        name = self._one_visible(page.get_by_role("heading", level=1)).inner_text().strip()
        if normalize_name(name) != normalize_name(review["expected_name"]):
            raise ReviewError(
                f"Business mismatch: Google opened '{name}'. Enter its exact business name and prepare again."
            )
        email = self._account(page)
        if email != review["account_email"]:
            self._state_update(status="error", email="", message="Google account changed. Check connection again.")
            raise ReviewError(
                "Google is signed into a different account. Nothing was posted."
            )
        key = business_key(page.url, name)
        if self.store.duplicate(review_id, key, email):
            raise ReviewError(
                "A posted or unconfirmed review already exists for this account and business. Check Google Maps first."
            )
        addresses = page.locator('[data-item-id="address"]')
        visible_addresses = [addresses.nth(i) for i in range(addresses.count())
                             if addresses.nth(i).is_visible()]
        address = ""
        if len(visible_addresses) == 1:
            address = visible_addresses[0].evaluate(
                """node => {
                    const label = node.getAttribute('aria-label') || '';
                    return /^Address:\\s*/i.test(label)
                        ? label.replace(/^Address:\\s*/i, '').trim()
                        : (node.querySelector('.Io6YTe')?.textContent.trim() || '');
                }"""
            )
        self.store.update(
            review_id,
            business_name=name,
            business_url=page.url,
            business_key=key,
            **business_location(page.url, address),
            message="Correct business and Google account verified. Opening the review form.",
        )
        if not self._checkpoint(review_id):
            return
        existing_pages = set(self._context.pages)
        self._one_visible(
            page.get_by_role("button", name=re.compile(r"^(Write a review|Rate and review)$", re.I))
        ).click()
        form_page, form = self._find_form(page, existing_pages)
        self._fill_form(form_page, form, review)
        if not self._checkpoint(review_id):
            return
        self._prepared[review_id] = (page, form_page, form)
        self.store.transition(
            review_id,
            "preparing",
            "ready",
            "Preview ready. Exact text and rating verified. Nothing has been submitted.",
        )
        form_page.bring_to_front()

    # ------------------------------------------------------------------
    # Find the review form (might open in a new tab or dialog)
    # ------------------------------------------------------------------
    def _find_form(self, original, existing_pages=None):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            matches = []
            for page in self._context.pages:
                if page != original:
                    parsed = urlsplit(page.url)
                    if (
                        page in (existing_pages or set())
                        or parsed.hostname not in {"google.com", "www.google.com", "search.google.com"}
                        or not any(
                            part in parsed.path for part in ("/maps", "/review", "/contribute", "writereview")
                        )
                    ):
                        continue
                dialogs = page.get_by_role("dialog")
                for i in range(dialogs.count()):
                    dialog = dialogs.nth(i)
                    if dialog.is_visible() and dialog.locator("textarea").count() == 1:
                        matches.append((page, dialog))
                if page != original and not dialogs.count() and page.locator("textarea").count() == 1:
                    matches.append((page, page.locator("body")))
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ReviewError(
                    "More than one review form is open. Close the extra forms and prepare again."
                )
            original.wait_for_timeout(300)
        raise ReviewError(
            "Google's review form was not found. Open the review manually in Google Maps."
        )

    # ------------------------------------------------------------------
    # Helper – click a specific rating
    # ------------------------------------------------------------------
    def _rating(self, form, stars):
        candidates = form.locator('[role="radio"], [data-rating], [aria-label*="star"], [aria-label*="Star"]')
        matches = []
        pattern = re.compile(rf"^(?:Rate\s+)?{stars}\s+stars?$", re.I)
        for i in range(candidates.count()):
            item = candidates.nth(i)
            label = (item.get_attribute("aria-label") or "").strip()
            if item.is_visible() and (pattern.fullmatch(label) or item.get_attribute("data-rating") == str(stars)):
                matches.append(item)
        if len(matches) != 1:
            raise ReviewError(
                "The requested rating cannot be selected unambiguously. Continue manually in Google Maps."
            )
        return matches[0]

    # ------------------------------------------------------------------
    # Helper – check if an element is selected
    # ------------------------------------------------------------------
    @staticmethod
    def _selected(item):
        return any(item.get_attribute(attr) == "true" for attr in ("aria-checked", "aria-pressed", "aria-selected"))

    # ------------------------------------------------------------------
    # Verify that the form matches the draft
    # ------------------------------------------------------------------
    def _verify_form(self, form, review):
        textarea = self._one_visible(form.locator("textarea"))
        if textarea.input_value() != review["text"]:
            raise ReviewError("The review text differs from your draft. Nothing was posted.")
        if not self._selected(self._rating(form, review["stars"])):
            raise ReviewError(
                "Google's selected rating could not be verified. Nothing was posted; finish manually in Google Maps."
            )

    # ------------------------------------------------------------------
    # Fill the form with rating and text
    # ------------------------------------------------------------------
    def _fill_form(self, page, form, review):
        rating = self._rating(form, review["stars"])
        rating.click()
        self._one_visible(form.locator("textarea")).fill(review["text"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self._selected(rating):
            page.wait_for_timeout(150)
        self._verify_form(form, review)

    # ------------------------------------------------------------------
    # Publish the prepared review
    # ------------------------------------------------------------------
    def _publish(self, review_id):
        review = self.store.get(review_id)
        if self._stop.is_set():
            raise ReviewError("The app stopped before submission. Nothing was posted.")
        if review_id not in self._prepared:
            raise ReviewError("The prepared form is no longer available. Prepare again.")
        original, page, form = self._prepared[review_id]
        if page.is_closed() or original.is_closed():
            raise ReviewError("The Google Maps window was closed. Nothing was posted.")
        self._check_google_page(original)
        name = self._one_visible(original.get_by_role("heading", level=1,
                                                    name=review["business_name"],
                                                    exact=True)).inner_text().strip()
        if (normalize_name(name) != normalize_name(review["business_name"])
                or business_key(original.url, name) != review["business_key"]):
            raise ReviewError("The business changed after preview. Nothing was posted.")
        if self._account(original) != review["account_email"]:
            raise ReviewError("The Google account changed after preview. Nothing was posted.")
        if page != original and self._account(page) != review["account_email"]:
            raise ReviewError(
                "The review window's Google account could not be verified. Nothing was posted."
            )
        self._verify_form(form, review)
        post = self._one_visible(form.get_by_role("button", name="Post", exact=True))
        if not post.is_enabled():
            raise ReviewError("Google's Post button is disabled. Nothing was posted.")
        self._random_delay()  # human‑like pause before clicking
        if self._stop.is_set():
            raise ReviewError("The app stopped before submission. Nothing was posted.")
        self.store.transition(
            review_id,
            "publishing",
            "submitting",
            "Submitting once. Waiting for Google's explicit confirmation.",
        )
        post.click(timeout=10000)
        confirmed = self._confirmed(page)
        self.store.transition(
            review_id,
            "submitting",
            "posted" if confirmed else "unconfirmed",
            "Google confirmed the submission. Google may still moderate its public visibility."
            if confirmed
            else "Google did not show a clear success message. Check contributions before posting again.",
        )
        self._prepared.pop(review_id, None)

    # ------------------------------------------------------------------
    # Check for a success message
    # ------------------------------------------------------------------
    @staticmethod
    def _confirmed(page):
        deadline = time.monotonic() + 15
        success = re.compile(
            r"^(Your review (?:has been|was) posted[.!]?|Review posted[.!]?|Thanks for your review[.!]?|Thank you for sharing[.!]?)$",
            re.I,
        )
        while time.monotonic() < deadline:
            labels = page.get_by_text(success, exact=True)
            if any(labels.nth(i).is_visible() for i in range(labels.count())):
                return True
            page.wait_for_timeout(250)
        return False

    # ------------------------------------------------------------------
    # Discard a prepared review
    # ------------------------------------------------------------------
    def _discard(self, review_id):
        prepared = self._prepared.pop(review_id, None)
        if prepared:
            original, page, _ = prepared
            for tab in {original, page}:
                if not tab.is_closed():
                    tab.close()

    # ------------------------------------------------------------------
    # Random delay helper (used to mimic human behaviour)
    # ------------------------------------------------------------------
    def _random_delay(self):
        low, high = self.cfg.get("delay_range", (2.0, 6.0))
        time.sleep(random.uniform(low, high))


# ----------------------------------------------------------------------
# Main entry point – for debugging only
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("Start the personal review dashboard with: python app.py")
