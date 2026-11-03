"""Exercise the real dashboard with an isolated fake browser worker."""
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from app import create_app


class UiWorker:
    def __init__(self, store):
        self.store = store
        self.actions = []

    def snapshot(self):
        return {"status": "connected", "email": "owner@example.com", "busy": False, "message": "Test fixture account connected."}

    def command(self, action, value=None):
        self.actions.append((action, value))
        if action == "prepare":
            self.store.transition(value, "queued", "preparing", "Fixture: checking the review")
            self.store.update(value, business_name="My Market", business_url="https://www.google.com/maps/place/My+Market",
                              business_key="place:fixture", business_address="Main Road, Karachi",
                              business_latitude=24.8607, business_longitude=67.0011)
            self.store.transition(value, "preparing", "ready", "Fixture: exact text and rating verified. Nothing submitted.")
        elif action == "publish":
            self.store.transition(value, "publishing", "submitting", "Fixture: submit once")
            self.store.transition(value, "submitting", "posted", "Fixture: confirmed")

    def cancel(self, review_id):
        self.store.update(review_id, status="cancelled", message="Cancelled")

    def close(self):
        pass


class DashboardTests(unittest.TestCase):
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
        self.app = create_app(self.directory.name, UiWorker)
        self.server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(f"http://127.0.0.1:{self.server.server_port}")
        self.page.get_by_text("Google connected", exact=True).wait_for()
        self.worker = self.app.extensions["review_worker"]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def fill_review(self, text="I visited today. Good service."):
        self.page.locator("#target").fill("My Market Karachi")
        self.page.locator("#expected_name").fill("My Market")
        self.page.get_by_role("radio", name="3 stars", exact=True).check()
        self.page.locator("#text").fill(text)

    def test_email_validation_and_google_login_request(self):
        self.page.locator("#email").fill("not an email")
        self.page.get_by_role("button", name="Open Google sign-in", exact=True).click()
        self.assertEqual(self.page.locator("#emailError").inner_text(), "Enter a valid Google email.")
        self.assertEqual(self.worker.actions, [])
        self.page.locator("#email").fill("owner@example.com")
        self.page.get_by_role("button", name="Open Google sign-in", exact=True).click()
        self.page.wait_for_function("() => !document.querySelector('#connectButton').disabled")
        self.assertIn(("login", "owner@example.com"), self.worker.actions)

    def test_linked_errors_receive_focus(self):
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.assertTrue(self.page.locator("#formErrors").is_visible())
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "formErrors")
        self.assertEqual(self.page.locator("#formErrors a").count(), 1)
        self.assertEqual(self.page.locator('#formErrors a[href="#target"]').count(), 1)

    def test_policy_advisories_preserve_text_and_allow_genuine_negative_reviews(self):
        text = 'Service was slow. Contact private@example.com.'
        self.page.locator('#text').fill(text)
        self.page.locator('#target').focus()
        self.page.locator('#policyWarnings').wait_for(state='visible')
        self.assertIn('Email address detected', self.page.locator('#policyWarnings').inner_text())
        self.assertEqual(self.page.locator('#text').input_value(), text)
        self.assertEqual(self.worker.actions, [])
        self.page.locator('#text').fill('Service was slow and the food was cold.')
        self.page.locator('#target').focus()
        self.page.locator('#policyWarnings').wait_for(state='hidden')
        self.page.locator('#policyGuide summary').click()
        self.assertIn('available appeal', self.page.locator('#policyGuide').inner_text())
        self.page.locator('#text').fill(text)
        self.page.locator('#target').focus()
        self.page.locator('#policyWarnings').wait_for(state='visible')
        folder = Path(__file__).resolve().parents[1] / 'test-results'
        folder.mkdir(exist_ok=True)
        for width in (375, 768, 1440):
            self.page.set_viewport_size({'width': width, 'height': 950})
            self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
            if width in (375, 1440):
                self.page.screenshot(path=str(folder / f'policy-guidance-{width}.png'), full_page=True)
        self.assertEqual(self.errors, [])

    def test_refresh_clears_draft_and_rating_keyboard_input(self):
        self.fill_review("Real visit.\nMy own words.")
        self.page.evaluate("localStorage.setItem('tasmee.personal-review.draft.v1', JSON.stringify({target:'old',expected_name:'Old',text:'old draft',stars:5}))")
        self.page.reload()
        for field in ("target", "expected_name", "text"):
            self.assertEqual(self.page.locator("#"+field).input_value(), "")
        self.assertEqual(self.page.locator('input[name="stars"]:checked').count(), 0)
        self.assertEqual(self.page.evaluate("localStorage.getItem('tasmee.personal-review.draft.v1')"), None)
        radio = self.page.get_by_role("radio", name="3 stars", exact=True)
        radio.check()
        radio.focus()
        self.page.keyboard.press("ArrowRight")
        self.assertTrue(self.page.get_by_role("radio", name="4 stars", exact=True).is_checked())

    def test_refresh_keeps_active_preview_and_terminal_history_but_clears_form(self):
        self.fill_review()
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.get_by_role("button", name="Post this review", exact=True).wait_for()
        self.assertFalse(self.page.locator('#previewDetails').evaluate('(node)=>node.open'))
        self.page.reload()
        self.page.get_by_role("button", name="Post this review", exact=True).wait_for()
        self.assertEqual(self.page.locator('#text').input_value(), '')
        self.assertTrue(self.page.locator('#target').is_disabled())
        self.page.get_by_role("button", name="Post this review", exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for()
        self.page.reload()
        self.page.get_by_text('Google connected',exact=True).wait_for()
        self.assertTrue(self.page.locator('#previewEmpty').is_visible())
        self.assertFalse(self.page.locator('#previewContent').is_visible())
        self.assertEqual(self.page.locator('#historyList .history-row').count(), 1)
        self.page.get_by_role('button',name='View My Market review, Success',exact=True).click()
        self.assertEqual(self.page.locator('#reviewStatus').inner_text(), 'Success')

    def test_preview_does_not_submit_and_final_post_is_once(self):
        text = "I visited today.\n<script>window.unexpected=true</script>"
        self.fill_review(text)
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.get_by_role("button", name="Post this review", exact=True).wait_for()
        self.page.locator('#previewDetails > summary').click()
        self.assertEqual(self.page.locator("#previewText").inner_text(), text)
        self.assertEqual(self.page.locator("#previewAddress").inner_text(), "Main Road, Karachi")
        self.assertEqual(self.page.locator("#previewCoordinates").inner_text(), "Place coordinates: 24.860700, 67.001100")
        self.assertEqual(self.page.evaluate("window.unexpected"), None)
        self.assertEqual(sum(action == "publish" for action, _ in self.worker.actions), 0)
        self.page.get_by_role("button", name="Post this review", exact=True).click()
        self.page.locator("#reviewStatus").get_by_text("Success", exact=True).wait_for()
        self.assertEqual(sum(action == "publish" for action, _ in self.worker.actions), 1)
        self.assertEqual(self.errors, [])

    def test_ready_preview_can_be_cancelled_without_posting(self):
        self.fill_review()
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.get_by_role("button", name="Cancel", exact=True).wait_for()
        self.page.get_by_role("button", name="Cancel", exact=True).click()
        self.page.locator("#reviewStatus").get_by_text("Cancelled", exact=True).wait_for()
        self.assertEqual(sum(action == "publish" for action, _ in self.worker.actions), 0)

    def test_success_clears_composer_but_keeps_history_and_details(self):
        self.fill_review()
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.get_by_role('button',name='Post this review',exact=True).click()
        self.page.locator('#reviewStatus').get_by_text('Success',exact=True).wait_for()
        for field in ('target','expected_name','text'):
            self.assertEqual(self.page.locator('#'+field).input_value(),'')
        self.assertEqual(self.page.locator('input[name="stars"]:checked').count(),0)
        self.assertIn('Form cleared',self.page.locator('#notice').inner_text())
        self.page.get_by_role('button',name='View My Market review, Success',exact=True).click()
        self.assertTrue(self.page.locator('#previewDetails').evaluate('node=>node.open'))
        self.assertTrue(self.page.locator('#activityDetails').evaluate('node=>node.open'))
        self.assertIn('I visited',self.page.locator('#previewText').inner_text())

    def test_pending_is_not_green_and_delete_confirmation_preserves_counts(self):
        self.fill_review()
        self.page.get_by_role('button',name='Start',exact=False).click()
        self.page.get_by_role('button',name='Post this review',exact=True).wait_for()
        store=self.app.extensions['review_store'];review=store.list_reviews()[0]
        store.update(review['id'],status='unconfirmed',message='Fixture pending')
        self.page.locator('#reviewStatus').get_by_text('Check Google Maps',exact=True).wait_for()
        self.assertEqual(self.page.locator('#text').input_value(),'I visited today. Good service.')
        self.assertNotIn('good',self.page.locator('#reviewStatus').get_attribute('class'))
        self.page.get_by_role('button',name='View My Market review, Check Google Maps',exact=True).click()
        self.assertTrue(self.page.locator('#previewDetails').evaluate('node=>node.open'))
        self.page.get_by_role('button',name='Delete local history for My Market',exact=True).click()
        self.page.get_by_role('button',name='Cancel',exact=True).click()
        self.assertEqual(store.count(),1)
        self.page.get_by_role('button',name='Delete local history for My Market',exact=True).click()
        self.page.get_by_role('button',name='Delete local data',exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#historyCount').textContent.includes('0 total')")
        self.assertEqual(store.count(),0)
        self.assertEqual(store.business_statistics()[0]['pending'],1)
        self.assertEqual(self.errors,[])

    def test_populated_preview_responsive_and_reduced_motion(self):
        self.fill_review()
        self.page.get_by_role("button", name="Start", exact=False).click()
        self.page.get_by_role("button", name="Post this review", exact=True).wait_for()
        self.page.locator('#previewDetails > summary').click()
        self.page.emulate_media(reduced_motion="reduce")
        for width in (375, 768, 1024, 1440):
            self.page.set_viewport_size({"width": width, "height": 950})
            self.assertEqual(self.page.evaluate("document.documentElement.scrollWidth"), width)
            self.assertTrue(self.page.get_by_role("button", name="Post this review", exact=True).is_visible())
        folder = Path(__file__).resolve().parents[1] / "test-results"
        folder.mkdir(exist_ok=True)
        self.page.screenshot(path=str(folder / "preview-fixture-desktop.png"), full_page=True)
        self.page.set_viewport_size({"width": 375, "height": 1000})
        self.page.screenshot(path=str(folder / "preview-fixture-mobile.png"), full_page=True)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
