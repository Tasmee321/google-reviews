"""Single-account Playwright review worker. Browser calls stay on one worker thread."""
import queue
import re
import threading
import time
import random
import logging
from concurrent.futures import Future, TimeoutError as FutureTimeout

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from review_store import MAP_HOSTS, ReviewError, business_location, normalize_name
from app_config import validate_config
from browser_options import launch_options
from city_location import load_city_locations, selected_location, apply_browser_location
from network_guard import UKNetworkGuard
from poster_network import PosterNetworkProtection
from diagnostics import Diagnostics

LOGGER = logging.getLogger(__name__)


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
class ReviewWorker(PosterNetworkProtection):
    extension_mode = False
    transport = "poster"
    capabilities = ["saved_checks", "account_selection", "business_resolution"]

    def __init__(self, store, cfg=None):
        """
        :param store:   ReviewStore instance
        :param cfg:     configuration dictionary from config.json
        """
        self.store = store
        self.cfg = validate_config(cfg or {})
        self.network_guard = UKNetworkGuard(self.cfg["network_guard"])
        self.diagnostics = Diagnostics()
        self.browser_kind = self.cfg["browser_channel"]
        self.browser_label = {"chrome": "Chrome", "msedge": "Edge", "chromium": "Chromium"}[self.browser_kind]
        self._city_points = load_city_locations() if self.cfg["city_geolocation"] else {}

        self._lock = threading.Lock()
        self._state = {"status": "disconnected", "email": "", "busy": False,
                       "transport": "poster", "browser_kind": self.browser_kind,
                       "capabilities": list(self.capabilities) + (["city_geolocation"] if self.cfg["city_geolocation"] else []),
                       "location": selected_location(self.cfg, self._city_points),
                       "message": "Connect your Google account to get started."}
        self._queue = queue.Queue(maxsize=1)
        self._thread = None
        self._stop = threading.Event()
        self._cancel = set()
        self._playwright = None
        self._context = None
        self._prepared = {}
        self._expected_email = ""
        self._account_indexes = {}

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return {**self._state, "location": dict(self._state["location"]), "network": self.network_guard.snapshot()}

    def _state_update(self, **values):
        with self._lock:
            self._state.update(values)

    # ------------------------------------------------------------------
    # Public API – queue a command
    # ------------------------------------------------------------------
    def command(self, action, value=None, wait=False):
        if action not in {"login", "check", "select", "prepare", "publish", "discard", "resolve", "saved_check", "location", "network"}:
            raise ReviewError("Unsupported browser action.")
        future = Future() if wait else None
        with self._lock:
            if self._stop.is_set():
                raise ReviewError("The browser worker has stopped. Restart the app.", 409)
            if self._state["busy"]:
                raise ReviewError("The browser is busy. Wait for the current action.", 409)
            self._state["busy"] = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="personal-review-browser",
                                                daemon=True)
                self._thread.start()
            self._queue.put_nowait((action, value, future))
        if future is not None:
            try:
                return future.result(timeout=180)
            except FutureTimeout as error:
                raise ReviewError("Browser action is still running. Wait for it to finish before retrying.", 504) from error

    def cancel(self, review_id):
        with self._lock:
            self._cancel.add(review_id)

    def close(self):
        self._stop.set()
        if self._thread:
            try:
                self._queue.put_nowait(("close", None, None))
            except queue.Full:
                pass
            self._thread.join(timeout=180)

    # ------------------------------------------------------------------
    # Main worker loop
    # ------------------------------------------------------------------
    def _run(self):
        try:
            while True:
                try:
                    action, value, future = self._queue.get(timeout=1)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    self._idle_network_check()
                    continue
                if action == "close" or self._stop.is_set():
                    if future is not None:
                        future.set_exception(ReviewError("The browser worker stopped.", 409))
                    break
                result = None
                failure = None
                try:
                    result = getattr(self, "_" + action)(value)
                except Exception as error:
                    self.diagnostics.record("browser_action_failed", action)
                    if isinstance(error, ReviewError):
                        message = str(error)
                    elif action in {"login", "check"}:
                        message = ("Google connection could not be checked. "
                                   "Open Google sign-in, complete it in the browser, then check again.")
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
                    elif action not in {"resolve", "saved_check", "location", "network"}:
                        self._state_update(status="error", message=message)
                    failure = error if isinstance(error, ReviewError) else ReviewError(message, 502)
                    if not isinstance(error, ReviewError):
                        LOGGER.error("Browser action %s failed (%s).", action, type(error).__name__)
                finally:
                    self._state_update(busy=False)
                if future is not None:
                    if failure:
                        future.set_exception(failure)
                    else:
                        future.set_result(result)
        finally:
            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
            if self._playwright:
                self._playwright.stop()

    # ------------------------------------------------------------------
    # Browser helper – persistent profile using the Windows network connection
    # ------------------------------------------------------------------
    def _ensure_browser(self):
        if self._context:
            try:
                self._context.cookies()
                return
            except Exception:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None
                self._prepared.clear()
        if self._playwright is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
        options = self.browser_launch_options()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.store.directory / "browser"), **options)
            self.network_guard.invalidate()
            self._context.set_default_timeout(self.cfg["timeouts"]["element_ms"])
            apply_browser_location(self._context, self.snapshot()["location"])
        except Exception as error:
            if self._context is not None:
                try:
                    self._context.close()
                finally:
                    self._context = None
            raise ReviewError(
                "Cannot open the configured browser. Run check_setup.bat, close another "
                "copy using this profile, and check browser_channel in config.json.") from error

    def browser_launch_options(self):
        options = launch_options(self.cfg, self._playwright.devices)
        options.pop("permissions", None)
        location = self.snapshot()["location"]
        if location["enabled"]:
            options["geolocation"] = {"latitude": location["latitude"], "longitude": location["longitude"]}
        return options

    def set_city_location(self, city):
        return self.command("location", city, wait=True)

    def _location(self, city):
        if self.store.active():
            raise ReviewError("Finish or cancel the current review before changing city location.", 409)
        current = self.snapshot()["location"]
        location = selected_location(self.cfg, self._city_points, city, current["revision"] + 1)
        if self._context is not None:
            try:
                apply_browser_location(self._context, location)
            except Exception as error:
                try:
                    self._context.close()
                finally:
                    self._context = None
                    self._prepared.clear()
                    self._state_update(status="disconnected", email="", message="Location could not be applied; the poster browser was closed. Check connection again.")
                raise ReviewError("City location was not applied. Reopen the poster browser and try again.", 502) from error
        self._state_update(location=location)
        return dict(location)

    # ------------------------------------------------------------------
    # Open a new page inside the context
    # ------------------------------------------------------------------
    def _new_page(self):
        self._ensure_browser()
        self._verify_network()
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
        if parsed.scheme != "https" or parsed.hostname not in MAP_HOSTS or not parsed.path.startswith("/maps"):
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
        self._verify_network(force=True)
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
                timeout=self.cfg["timeouts"]["navigation_ms"],
            )
        except BrowserTimeout as error:
            raise ReviewError(
                "Google sign-in took too long to load. Check the browser window and your "
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
            query = {"hl": "en", "gl": "gb"}
            if self._expected_email:
                query["authuser"] = self._expected_email
            page.goto("https://www.google.com/maps?" + urlencode(query),
                      wait_until="domcontentloaded",
                      timeout=self.cfg["timeouts"]["navigation_ms"])
            self._consent(page)
            try:
                page.locator(
                    '[aria-label*="Google Account"], [aria-label*="Google account"]'
                ).first.wait_for(
                    state="visible", timeout=15000
                )
            except BrowserTimeout as error:
                raise ReviewError(
                    "Google sign-in was not detected. Enter your email and click Open "
                    "Google sign-in, finish password/2FA in Google's window, then "
                    "Check connection."
                ) from error
            email = self._account(page)
            if self._expected_email and email != self._expected_email:
                raise ReviewError(
                    "The browser is signed into a different account. Switch accounts "
                    "in Google Maps."
                )
            index = parse_qs(urlsplit(page.url).query).get("authuser", [""])[0]
            if index.isdecimal():
                self._account_indexes[email] = index
            self.store.remember_account(email)
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

    def _select(self, email):
        self._expected_email = email
        self._check(None)

    def _account_url(self, url, email):
        parsed = urlsplit(url)
        if parsed.hostname in {"maps.app.goo.gl", "goo.gl"}:
            return url
        query = parse_qs(parsed.query, keep_blank_values=True)
        if email in self._account_indexes:
            query["authuser"] = [self._account_indexes[email]]
        elif self._expected_email == email:
            query["authuser"] = [email]
        query["hl"], query["gl"] = ["en"], ["gb"]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))

    def _navigate_business(self, page, url, email):
        page.goto(self._account_url(url, email), wait_until="domcontentloaded",
                  timeout=self.cfg["timeouts"]["navigation_ms"])
        if urlsplit(url).hostname in {"maps.app.goo.gl", "goo.gl"}:
            self._check_google_page(page)
            destination = self._account_url(page.url, email)
            if destination != page.url:
                page.goto(destination, wait_until="domcontentloaded",
                          timeout=self.cfg["timeouts"]["navigation_ms"])

    def resolve_business(self, url, email):
        return self.command("resolve", (url, email), wait=True)

    def _resolve(self, request):
        from poster_pages import business_details
        url, email = request
        page = self._new_page()
        try:
            self._navigate_business(page, url, email)
            self._consent(page)
            self._check_google_page(page)
            return business_details(page, email, self.cfg["timeouts"]["element_ms"])
        finally:
            page.close()

    def inspect_saved(self, review_id, automatic=False):
        return self.command("saved_check", (review_id, automatic), wait=True)

    def _saved_check(self, request):
        from poster_pages import saved_review
        review_id, automatic = request
        review = self.store.get(review_id)
        state = self.snapshot()
        if self.store.active() or state["status"] != "connected" or state["email"] != review["account_email"]:
            raise ReviewError("Saved checks need this review's connected account and no active review.", 409)
        if automatic:
            self.store.claim_auto_check(review_id)
        page = None
        try:
            page = self._new_page()
            self._navigate_business(page, review["business_url"], review["account_email"])
            self._consent(page)
            proof = saved_review(page, review, self.cfg["timeouts"]["element_ms"])
            self.store.record_saved_check(review_id, True,
                "Saved review verified against account, business, exact text and rating. Public visibility remains unknown.", proof)
        except Exception:
            self.store.record_saved_check(review_id, False,
                "Saved review could not be verified. This does not prove deletion; nothing was reposted.")
            raise
        finally:
            if page is not None:
                page.close()
        return self.store.get(review_id)

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
        self._navigate_business(page, review["navigation_url"], review["account_email"])
        self._consent(page)
        self._random_delay()
        from poster_pages import business_details
        info = business_details(page, review["account_email"], self.cfg["timeouts"]["element_ms"])
        name, email, address = info["name"], info["email"], info["address"]
        if normalize_name(name) != normalize_name(review["expected_name"]):
            raise ReviewError(
                f"Business mismatch: Google opened '{name}'. Enter its exact business name and prepare again.")
        key = business_key(page.url, name)
        if self.store.duplicate(review_id, key, email):
            raise ReviewError(
                "A posted or unconfirmed review already exists for this account and business. Check Google Maps first.")
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
        from poster_pages import validate_widget
        validate_widget(form, page, review)
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
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    parsed_frame = urlsplit(frame.url)
                    if (parsed_frame.path == "/maps/api/js/ReviewsService.LoadWriteWidget"
                            and frame.locator("textarea").count() == 1
                            and frame.locator("textarea").is_visible()):
                        matches.append((page, frame.locator("body")))
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
        overall = form.get_by_role("radiogroup", name="Rating stars", exact=True)
        if overall.count():
            form = self._one_visible(overall)
        candidates = form.locator('[role="radio"], [data-rating], [aria-label*="star"], [aria-label*="Star"]')
        matches = []
        words = ("", "One", "Two", "Three", "Four", "Five")
        pattern = re.compile(rf"^(?:Rate\s+)?(?:{stars}|{words[stars]})\s+stars?$", re.I)
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
        if any(self._selected(self._rating(form, stars)) for stars in range(1, 6) if stars != review["stars"]):
            raise ReviewError("More than one overall rating is selected. Nothing was posted.")

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
        self._random_delay()
        # Check routing before the final account/text/rating checks to avoid validating stale form data.
        self._verify_network(force=True)
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
        from poster_pages import validate_widget
        validate_widget(form, original, review)
        self._verify_form(form, review)
        post = self._one_visible(form.get_by_role("button", name="Post", exact=True))
        if not post.is_enabled():
            raise ReviewError("Google's Post button is disabled. Nothing was posted.")
        if self._stop.is_set():
            raise ReviewError("The app stopped before submission. Nothing was posted.")
        if self.network_guard.enabled and not self.network_guard.snapshot()["allowed"]:
            raise ReviewError("UK-IP check expired before submission. Nothing was posted; check the connection and prepare again.", 409)
        self.store.transition(
            review_id,
            "publishing",
            "submitting",
            "Submitting once. Waiting for Google's explicit confirmation.",
        )
        post.click(timeout=10000)
        confirmed = self._confirmed(page)
        if not confirmed:
            try:
                from poster_pages import saved_review
                saved_review(original, review, timeout=1000)
                confirmed = True
            except Exception:
                pass
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
    # Optional bounded pacing; default has no added delay
    # ------------------------------------------------------------------
    def _random_delay(self):
        low, high = self.cfg["delay_range"]
        self._stop.wait(random.uniform(low, high))


# ----------------------------------------------------------------------
# Main entry point – for debugging only
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("Start the personal review dashboard with: python app.py")
