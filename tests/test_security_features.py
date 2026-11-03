"""Protection integration using intercepted browser pages, never live accounts/reviews."""
import tempfile
import time
import unittest
from unittest.mock import patch

from app import create_app
from local_security import LocalSecurityError
from review_store import ReviewError, validate_review
from test_poster_integration import InterceptedWorker, TARGET, TEXT


class ProtectedPosterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(self.temp.name, InterceptedWorker, config={})
        self.worker = self.app.extensions['review_worker']
        self.addCleanup(self.worker.close)
        self.store = self.app.extensions['review_store']
        self.client = self.app.test_client()
        self.client.post('/api/unlock', json={'token': self.app.extensions['dashboard_token']})
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token': session['csrf']}

    def post(self, url, data):
        return self.client.post(url, json=data, headers=self.headers)

    def ready(self):
        self.worker.command('check', wait=True)
        review = self.store.create(validate_review({'target': TARGET, 'expected_name': 'My Market',
            'account_email': 'owner@example.com', 'stars': 4, 'text': TEXT}))
        self.worker.command('prepare', review['id'], wait=True)
        return self.store.get(review['id'])

    def wait_idle(self):
        deadline = time.monotonic() + 15
        while self.worker.snapshot()['busy'] and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(self.worker.snapshot()['busy'])

    def test_default_city_picker_is_search_only_and_storage_is_protected(self):
        self.assertFalse(self.worker.snapshot()['location']['enabled'])
        self.assertEqual(self.app.extensions['local_protection']['status'], 'protected')
        self.assertEqual(self.post('/api/browser/location', {'city': 'London, England, United Kingdom'}).status_code, 409)

    def test_uk_check_opens_no_google_account_and_needs_csrf(self):
        self.assertEqual(self.client.post('/api/browser/network', json={}).status_code, 403)
        result = self.post('/api/browser/network', {})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['network']['allowed'])
        self.assertEqual(self.worker.snapshot()['status'], 'disconnected')
        self.assertEqual(self.worker.snapshot()['email'], '')
        self.assertEqual(self.worker.submissions, 0)

    def test_non_uk_or_unavailable_network_blocks_login_and_closes_browser(self):
        for country, unavailable in (('PK', False), ('GB', True)):
            self.worker.network_country = country
            self.worker.network_unavailable = unavailable
            with self.assertRaises(ReviewError):
                self.worker.command('login', 'owner@example.com', wait=True)
            self.assertIsNone(self.worker._context)
            self.assertFalse(self.worker.snapshot()['network']['allowed'])
            self.assertEqual(self.worker.submissions, 0)

    def test_network_loss_before_post_interrupts_without_submission_or_retry(self):
        review = self.ready()
        self.worker.network_country = 'PK'
        result = self.post(f"/api/reviews/{review['id']}/publish", {
            'confirmation_token': review['confirmation_token'], 'policy_confirmed': True})
        self.assertEqual(result.status_code, 202)
        self.wait_idle()
        self.assertEqual(self.worker.submissions, 0)
        self.assertEqual(self.store.get(review['id'])['status'], 'failed')
        self.assertIsNone(self.worker._context)

    def test_expired_sample_after_final_form_validation_never_clicks_post(self):
        review = self.ready()
        verify = self.worker._verify_form
        def expire_after_verify(form, current):
            verify(form, current)
            self.worker.network_guard.invalidate()
        with patch.object(self.worker, '_verify_form', side_effect=expire_after_verify):
            result = self.post(f"/api/reviews/{review['id']}/publish", {
                'confirmation_token': review['confirmation_token'], 'policy_confirmed': True})
            self.assertEqual(result.status_code, 202)
            self.wait_idle()
        self.assertEqual(self.worker.submissions, 0)
        self.assertEqual(self.store.get(review['id'])['status'], 'failed')
        self.assertNotIn('submitting', [event.get('status') for event in self.store.get(review['id'])['events']])

    def test_idle_guard_closes_existing_browser_after_failed_sample(self):
        self.worker.command('check', wait=True)
        self.worker.network_country = 'US'
        self.worker.network_guard.invalidate()
        deadline = time.monotonic() + 10
        while self.worker._context is not None and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertIsNone(self.worker._context)
        self.wait_idle()
        self.assertEqual(self.worker.snapshot()['status'], 'disconnected')

    def test_final_consent_and_contact_policy_are_server_enforced(self):
        review = self.ready()
        endpoint = f"/api/reviews/{review['id']}/publish"
        token = {'confirmation_token': review['confirmation_token']}
        self.assertEqual(self.post(endpoint, token).status_code, 400)
        self.assertEqual(self.post(endpoint, {**token, 'policy_confirmed': 'true'}).status_code, 400)
        self.assertEqual(self.store.get(review['id'])['status'], 'ready')
        self.assertEqual(self.worker.submissions, 0)
        with self.store.connect() as db:
            db.execute('UPDATE reviews SET text=? WHERE id=?', ('Contact private@example.com', review['id']))
        self.assertEqual(self.post(endpoint, {**token, 'policy_confirmed': True}).status_code, 400)
        self.assertEqual(self.worker.submissions, 0)

    def test_cross_account_warning_survives_local_detail_deletion(self):
        previous = self.store.create(validate_review({'target': TARGET, 'expected_name': 'My Market',
            'account_email': 'different@example.com', 'stars': 3, 'text': 'Different genuine experience.'}))
        self.store.update(previous['id'], status='posted', business_key='place:fixture')
        self.assertTrue(self.store.has_other_account_review('place:fixture', 'owner@example.com'))
        self.store.delete_history(previous['id'])
        self.assertTrue(self.store.has_other_account_review('place:fixture', 'owner@example.com'))
        self.assertFalse(self.store.has_other_account_review('place:fixture', 'different@example.com'))

    def test_diagnostics_download_redacts_details_and_reports_protection(self):
        self.worker._state_update(email='private@example.com', message='secret-cookie-and-path')
        response = self.client.get('/api/diagnostics?download=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        for private in ('private@example.com', 'secret-cookie-and-path', self.temp.name):
            self.assertNotIn(private, response.text)
        self.assertEqual(response.json['local_storage']['status'], 'protected')

    def test_cross_scheme_origin_is_rejected(self):
        result = self.client.post('/api/browser/network', json={}, headers={**self.headers, 'Origin': 'https://localhost'})
        self.assertEqual(result.status_code, 403)

    def test_startup_fails_before_store_or_browser_if_permissions_fail(self):
        with patch('app.secure_data_directory', side_effect=LocalSecurityError('permissions', 'Protection failed')), patch('app.ReviewStore') as store:
            with self.assertRaises(LocalSecurityError):
                create_app(self.temp.name, config={})
            store.assert_not_called()

    def test_legacy_extension_cannot_silently_bypass_enabled_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder, config={'mode': 'extension'})
            self.addCleanup(app.extensions['review_worker'].close)
            client = app.test_client()
            client.post('/api/unlock', json={'token': app.extensions['dashboard_token']})
            client.get('/')
            with client.session_transaction() as session:
                headers = {'X-CSRF-Token': session['csrf']}
            self.assertEqual(client.post('/api/browser/login', json={'email': 'owner@example.com'}, headers=headers).status_code, 409)


if __name__ == '__main__':
    unittest.main()
