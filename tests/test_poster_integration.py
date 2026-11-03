"""Real poster worker + dashboard, using intercepted Google fixtures only."""
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from app import create_app
from browser_options import launch_options
from poster import ReviewWorker
from test_normal_chrome import GOOGLE, RADIOS, SAVED_CARD, WIDGET, WIDGET_RADIOS, WIDGET_URL

TEXT = "My genuine visit.\nThe staff were helpful."
TARGET = "https://www.google.com/maps/place/My+Market/data=!1sfixture"
IFRAME_PAGE = '''<!doctype html><html><body>
<button aria-label="Google Account: Test (owner@example.com)">Account</button>
<h1 class="DUwDvf">My Market</h1><button data-item-id="address" aria-label="Address: Manchester, UK">Address</button>
<button onclick="document.querySelector('#writer').hidden=false">Write a review</button>
<iframe id="writer" hidden src="{widget}" style="width:700px;height:500px"></iframe>
<p id="result"></p><script>window.posts=0;window.addEventListener('message',event=>{{
 if(event.data?.type==='FIXTURE_POSTED'){{window.posts++;document.querySelector('#writer').remove();
 document.querySelector('#result').textContent='Your review has been posted.';}}
}});</script></body></html>'''


class InterceptedWorker(ReviewWorker):
    def __init__(self, store, cfg):
        super().__init__(store, cfg)
        self.iframe = False
        self.saved = False
        self.submissions = 0
        self.external = []
        self.extra_ratings = None

    def _ensure_browser(self):
        if self._context is not None:
            return
        self._playwright = sync_playwright().start()
        options = launch_options(self.cfg, self._playwright.devices)
        options["headless"] = True
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self.store.directory / "fixture-browser"), **options)
        self._context.set_default_timeout(5000)
        self._context.route("**/*", self._route)

    def _route(self, route):
        parsed = urlsplit(route.request.url)
        if parsed.hostname not in {"www.google.com", "accounts.google.com"}:
            self.external.append(route.request.url)
            route.abort()
            return
        query = parse_qs(parsed.query)
        if "@" in query.get("authuser", [""])[0]:
            query["authuser"] = ["0"]
            location = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))
            route.fulfill(status=302, headers={"location": location})
            return
        if parsed.path == "/maps/api/js/ReviewsService.LoadWriteWidget":
            body = WIDGET.format(radios=WIDGET_RADIOS)
        else:
            body = IFRAME_PAGE.format(widget=WIDGET_URL) if self.iframe else GOOGLE.format(radios=RADIOS)
            if self.saved:
                body = body.replace("</body>", SAVED_CARD + "</body>")
        route.fulfill(body=body, content_type="text/html")

    def _publish(self, review_id):
        original, _, form = self._prepared[review_id]
        self.extra_ratings = form.locator('[aria-label="Food rating stars"] [aria-checked="true"]').count()
        super()._publish(review_id)
        self.submissions += original.evaluate("window.posts")
        self.saved = self.store.get(review_id)["status"] == "posted"


class PosterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, InterceptedWorker, config={"mode": "poster"})
        self.worker = self.app.extensions["review_worker"]
        self.addCleanup(self.worker.close)
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.requests = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda request: self.requests.append(request.post_data_json)
                     if request.url.endswith("/api/business/resolve") else None)
        self.page.goto(f"http://127.0.0.1:{self.server.server_port}/")
        self.page.get_by_role("button", name="Check connection", exact=True).click()
        self.page.get_by_text("Google connected", exact=True).wait_for()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def prepare(self, target="My Market"):
        self.page.locator("#searchCity").select_option("Manchester, England, United Kingdom")
        self.page.locator("#target").fill(target)
        self.page.get_by_role("radio", name="4 stars", exact=True).check()
        self.page.locator("#text").fill(TEXT)
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.get_by_role("button", name="Post this review", exact=True).wait_for()

    def test_city_search_poster_submission_and_read_only_saved_check(self):
        self.prepare()
        self.assertEqual(self.requests[-1]["target"], "My Market, Manchester, England, United Kingdom")
        self.assertFalse(self.page.locator("#extensionSetup").is_visible())
        self.assertEqual(self.worker.submissions, 0)
        self.page.get_by_role("button", name="Post this review", exact=True).click()
        self.page.locator("#reviewStatus").get_by_text("Success", exact=True).wait_for()
        self.assertEqual(self.worker.submissions, 1)
        self.assertEqual(self.page.locator("#text").input_value(), "")
        self.page.get_by_role("button", name="Check saved status", exact=True).click()
        self.page.locator("#savedStatus").get_by_text("Saved · verified", exact=True).wait_for()
        self.assertEqual(self.worker.submissions, 1)
        self.assertEqual(self.worker.external, [])
        self.assertEqual(self.errors, [])

    def test_iframe_overall_rating_only_and_single_post(self):
        self.worker.iframe = True
        self.prepare(TARGET)
        self.assertEqual(self.requests[-1]["target"], TARGET)
        self.page.get_by_role("button", name="Post this review", exact=True).click()
        self.page.locator("#reviewStatus").get_by_text("Success", exact=True).wait_for()
        self.assertEqual(self.worker.submissions, 1)
        self.assertEqual(self.worker.extra_ratings, 0)
        self.assertEqual(self.errors, [])

    def test_city_picker_preserves_links_and_responsive_layout(self):
        self.assertEqual(self.page.locator("#searchCity option").count(), 77)
        self.page.locator("#searchCity").select_option("Bangor, Northern Ireland, United Kingdom")
        self.page.locator("#target").fill(TARGET)
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.wait_for_function("() => document.querySelector('#expected_name').value === 'My Market'")
        self.assertEqual(self.requests[-1]["target"], TARGET)
        self.assertEqual(self.app.extensions["review_store"].count(), 0)
        folder = Path(__file__).resolve().parents[1] / "test-results"
        folder.mkdir(exist_ok=True)
        for width in (375, 768, 1024, 1440):
            self.page.set_viewport_size({"width": width, "height": 1000})
            self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth"), width)
        self.page.screenshot(path=str(folder / "poster-uk-desktop.png"), full_page=True)
        self.page.set_viewport_size({"width": 375, "height": 1000})
        self.page.screenshot(path=str(folder / "poster-uk-mobile.png"), full_page=True)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
