"""Real Chrome, intercepted Google URL fixtures. No external posting or credentials."""
import html
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from poster import ReviewWorker
from review_store import ReviewError, ReviewStore, validate_review

TARGET = "https://www.google.com/maps/place/My+Market/data=!1splace123"


def fixture(name="My Market", email="owner@example.com", selected=True, popup=False, popup_form=False):
    radios = "".join(f'<button role="radio" aria-label="{i} star{"s" if i > 1 else ""}" aria-checked="false" '
                     f'onclick="selectRating(this)">{i}</button>' for i in range(1, 6))
    return f'''<!doctype html><html lang="en"><body>
      <button aria-label="Google Account: Test ({html.escape(email)})">Account</button>
      {'' if popup_form else f'<h1>{html.escape(name)}</h1>'}
      <button data-item-id="address" aria-label="Address: Main Road, Karachi">Main Road, Karachi</button>
      <button onclick="{'window.open(\'https://www.google.com/maps/review/popup\')' if popup else 'document.querySelector(\'#writer\').hidden=false'}">Write a review</button>
      <div id="writer" role="dialog" {'' if popup_form else 'hidden'}><h2>Rate and review</h2>{radios}
      <textarea aria-label="Your review"></textarea>
      <button onclick="window.posts++;document.querySelector('#result').textContent='Your review has been posted.';document.querySelector('#writer').hidden=true">Post</button></div>
      <p id="result"></p><script>
      window.posts=0;
      function selectRating(button) {{
        {'document.querySelectorAll(\'[role="radio"]\').forEach(r=>r.setAttribute(\'aria-checked\',\'false\'));button.setAttribute(\'aria-checked\',\'true\');' if selected else ''}
      }}
      </script></body></html>'''


class BrowserFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.store = ReviewStore(self.directory.name)
        self.worker = ReviewWorker(self.store)
        self.worker._context = self.context
        self.page_html = fixture()
        self.context.route("https://www.google.com/**", lambda route: route.fulfill(
            content_type="text/html", body=fixture(popup_form=True) if "/review/popup" in route.request.url else self.page_html))

    def create_review(self, **changes):
        return self.store.create(validate_review({"target": TARGET, "expected_name": "My Market",
            "account_email": "owner@example.com", "stars": 4,
            "text": "My actual visit.\nThe service was good & friendly.", **changes}))

    def prepare(self, **changes):
        review = self.create_review(**changes)
        self.worker._prepare(review["id"])
        return self.store.get(review["id"])

    def publish(self, review):
        self.store.transition(review["id"], "ready", "publishing", "Confirm")
        self.worker._publish(review["id"])

    def test_all_five_ratings_and_exact_text_then_confirmed_submission(self):
        for stars in range(1, 6):
            review = self.prepare(stars=stars)
            original, page, form = self.worker._prepared[review["id"]]
            self.assertEqual(review["status"], "ready")
            self.assertEqual(page.evaluate("window.posts"), 0)
            self.assertEqual(form.locator("textarea").input_value(), review["text"])
            self.publish(review)
            self.assertEqual(page.evaluate("window.posts"), 1)
            self.assertEqual(self.store.get(review["id"])["status"], "posted")
            # Separate fixture business ids to test each rating without bypassing duplicate checks.
            self.store.update(review["id"], business_key=f"place:rating{stars}")
            page.close()

    def test_business_mismatch_stops_before_opening_form(self):
        self.page_html = fixture(name="Other Business")
        review = self.create_review()
        with self.assertRaisesRegex(ReviewError, "Business mismatch"):
            self.worker._prepare(review["id"])
        self.assertEqual(self.context.pages[0].evaluate("window.posts"), 0)
        self.assertFalse(self.context.pages[0].locator("#writer").is_visible())

    def test_business_location_is_saved_from_selected_place(self):
        review = self.prepare(target=TARGET + "!3d24.8607!4d67.0011")
        self.assertEqual(review["business_address"], "Main Road, Karachi")
        self.assertEqual(review["business_latitude"], 24.8607)
        self.assertEqual(review["business_longitude"], 67.0011)

    def test_wrong_google_account_stops(self):
        self.page_html = fixture(email="other@example.com")
        review = self.create_review()
        with self.assertRaisesRegex(ReviewError, "different account"):
            self.worker._prepare(review["id"])
        self.assertEqual(self.context.pages[0].evaluate("window.posts"), 0)

    def test_unverifiable_rating_never_posts(self):
        self.page_html = fixture(selected=False)
        review = self.create_review()
        with self.assertRaisesRegex(ReviewError, "rating could not be verified"):
            self.worker._prepare(review["id"])
        self.assertEqual(self.context.pages[0].evaluate("window.posts"), 0)

    def test_text_changed_after_preview_never_posts(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        page.locator("textarea").fill("Different review")
        with self.assertRaisesRegex(ReviewError, "text differs"):
            self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 0)

    def test_text_changed_during_configured_pacing_never_posts(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        with patch.object(self.worker, "_random_delay", side_effect=lambda: page.locator("textarea").fill("Changed during delay")):
            with self.assertRaisesRegex(ReviewError, "text differs"):
                self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 0)

    def test_two_selected_overall_ratings_never_post(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        page.get_by_role("radio", name="1 star", exact=True).evaluate("node=>node.setAttribute('aria-checked','true')")
        with self.assertRaisesRegex(ReviewError, "More than one overall rating"):
            self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 0)

    def test_rating_changed_after_preview_never_posts(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        page.get_by_role("radio", name="1 star", exact=True).click()
        with self.assertRaisesRegex(ReviewError, "rating could not be verified"):
            self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 0)

    def test_account_changed_after_preview_never_posts(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        page.locator('[aria-label*="Google Account"]').evaluate("e=>e.setAttribute('aria-label','Google Account: Other (other@example.com)')")
        with self.assertRaisesRegex(ReviewError, "account changed"):
            self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 0)

    def test_popup_review_form(self):
        self.page_html = fixture(popup=True)
        review = self.prepare()
        original, page, form = self.worker._prepared[review["id"]]
        self.assertNotEqual(original, page)
        self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 1)

    def test_no_success_signal_is_unconfirmed_not_success(self):
        review = self.prepare()
        page = self.worker._prepared[review["id"]][1]
        page.locator("#writer button").last.evaluate("e=>e.onclick=()=>{window.posts++;document.querySelector('#writer').hidden=true}")
        with patch("poster.time.monotonic", side_effect=[0, 16]):
            self.assertFalse(self.worker._confirmed(page))
        with patch.object(self.worker, "_confirmed", return_value=False):
            self.publish(review)
        self.assertEqual(page.evaluate("window.posts"), 1)
        self.assertEqual(self.store.get(review["id"])["status"], "unconfirmed")

    def test_closed_browser_does_not_submit(self):
        review = self.prepare()
        self.worker._prepared[review["id"]][1].close()
        with self.assertRaisesRegex(ReviewError, "window was closed"):
            self.publish(review)


if __name__ == "__main__":
    unittest.main()
