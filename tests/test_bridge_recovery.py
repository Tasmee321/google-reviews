"""Deterministic timeout/race regressions against temporary data; never contacts Google."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app import create_app
from review_store import maps_url, ReviewError


class BridgeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = 1000
        clock = patch('browser_bridge.time.monotonic', side_effect=lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        with patch.dict('os.environ', {'REVIEW_BROWSER': 'firefox'}):
            self.app = create_app(self.directory.name, config={"mode": "extension"})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token': session['csrf']}
        self.worker = self.app.extensions['review_worker']
        self.store = self.app.extensions['review_store']
        self.identity = {'email': 'owner@example.com', 'browser_kind': 'firefox'}
        self.assertEqual(self.post('/api/browser/verified', self.identity).status_code, 200)

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def draft(self, place='fixture'):
        response = self.post('/api/reviews', {
            'target': 'https://www.google.com/maps/place/Market/data=!1s' + place,
            'expected_name': 'Market', 'account_email': 'owner@example.com',
            'text': 'My own experience.', 'stars': 3})
        self.assertEqual(response.status_code, 202)
        return response.json['review']

    def proof(self, review, **changes):
        return {'email': review['account_email'], 'name': review['expected_name'],
                'url': review['navigation_url'], 'text': review['text'], 'stars': review['stars'], **changes}

    def callback(self, review, action, **data):
        return self.post('/api/reviews/' + review['id'] + '/' + action,
                         {'confirmation_token': review['confirmation_token'], **data})

    def ready(self):
        review = self.draft()
        self.assertEqual(self.callback(review, 'prepared', assertion=self.proof(review)).status_code, 200)
        return review

    def publishing(self):
        review = self.ready()
        self.assertEqual(self.callback(review, 'publish').status_code, 202)
        return review

    def expire(self):
        self.clock += self.worker.ACTION_TIMEOUT + 1

    def test_abandoned_preparation_expires_without_restart(self):
        review = self.draft()
        self.expire()
        self.assertFalse(self.worker.snapshot()['busy'])
        self.assertEqual(self.store.get(review['id'])['status'], 'interrupted')
        self.assertIsNone(self.worker.operation)
        self.draft()

    def test_publishing_expiry_blocks_late_submit_authorization(self):
        review = self.publishing()
        self.expire()
        # No status poll is required to reject an expired callback.
        self.assertEqual(self.callback(review, 'submitting', assertion=self.proof(review)).status_code, 409)
        self.assertEqual(self.store.get(review['id'])['status'], 'interrupted')
        self.assertFalse(self.worker.snapshot()['busy'])

    def test_submission_expiry_keeps_uncertainty_and_duplicate_protection(self):
        review = self.publishing()
        self.assertEqual(self.callback(review, 'submitting', assertion=self.proof(review)).status_code, 200)
        self.expire()
        self.assertFalse(self.worker.snapshot()['busy'])
        saved = self.store.get(review['id'])
        self.assertEqual(saved['status'], 'unconfirmed')
        self.assertTrue(self.store.duplicate('new', saved['business_key'], saved['account_email']))
        other = self.draft()
        self.assertEqual(self.callback(other, 'prepared', assertion=self.proof(other)).status_code, 409)

    def test_late_result_does_not_mark_timeout_success(self):
        review = self.publishing()
        self.callback(review, 'submitting', assertion=self.proof(review))
        self.expire()
        self.assertEqual(self.callback(review, 'result', confirmed=True).status_code, 409)
        self.assertEqual(self.store.get(review['id'])['status'], 'unconfirmed')

    def test_late_failure_and_finish_cannot_unlock_a_new_job(self):
        old = self.publishing()
        self.expire()
        self.worker.snapshot()
        current = self.draft('another-place')
        self.assertEqual(self.callback(old, 'failure', message='Old response').status_code, 409)
        self.worker.finish(old['id'])
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.worker.operation['id'], current['id'])

    def test_submitting_renews_the_phase_deadline(self):
        review = self.publishing()
        self.clock += self.worker.ACTION_TIMEOUT - 1
        self.assertEqual(self.callback(review, 'submitting', assertion=self.proof(review)).status_code, 200)
        self.clock += 2
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.callback(review, 'result', confirmed=True).status_code, 200)
        self.assertEqual(self.store.get(review['id'])['status'], 'posted')
        self.assertIsNone(self.worker.operation)

    def test_ready_preview_does_not_expire_while_waiting_for_person(self):
        review = self.ready()
        self.expire()
        self.assertFalse(self.worker.snapshot()['busy'])
        self.assertEqual(self.store.get(review['id'])['status'], 'ready')
        self.assertEqual(self.callback(review, 'publish').status_code, 202)

    def test_expiry_waits_for_callback_transaction(self):
        review = self.draft()
        started = threading.Event()
        def poll():
            started.set()
            return self.worker.snapshot()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.worker.review_action(review['id']):
                self.expire()
                future = executor.submit(poll)
                self.assertTrue(started.wait(2))
                self.assertFalse(future.done())
                self.store.transition(review['id'], 'preparing', 'ready', 'Verified fixture')
                self.worker.finish(review['id'])
            self.assertFalse(future.result(timeout=2)['busy'])
        self.assertEqual(self.store.get(review['id'])['status'], 'ready')

    def test_cancellation_rejects_late_prepared_callback(self):
        review = self.draft()
        self.assertEqual(self.callback(review, 'cancel').status_code, 200)
        self.assertEqual(self.callback(review, 'prepared', assertion=self.proof(review)).status_code, 409)
        self.assertEqual(self.store.get(review['id'])['status'], 'cancelled')
        self.assertFalse(self.worker.snapshot()['busy'])

    def saved_check(self):
        review = self.publishing()
        self.callback(review, 'submitting', assertion=self.proof(review))
        self.callback(review, 'result', confirmed=True)
        reserved = self.callback(review, 'check-start')
        self.assertEqual(reserved.status_code, 200)
        return review, reserved.json['verification_token']

    def test_reconnect_does_not_release_saved_check_or_change_account(self):
        review, token = self.saved_check()
        for email in ('owner@example.com', 'other@example.com'):
            self.assertEqual(self.post('/api/browser/verified', {**self.identity, 'email': email}).status_code, 409)
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.worker.snapshot()['email'], 'owner@example.com')
        self.assertEqual(self.worker.verification['token'], token)
        self.assertEqual(self.post('/api/browser/select', {'email': 'owner@example.com'}).status_code, 409)
        self.assertEqual(self.callback(review, 'check-result', verification_token=token, matched=False).status_code, 200)
        self.assertEqual(self.post('/api/browser/verified', self.identity).status_code, 200)

    def test_old_saved_check_release_cannot_clear_new_reservation(self):
        review, old_token = self.saved_check()
        self.clock += 121
        self.worker.snapshot()
        new_token = self.worker.reserve_check(review['id'])
        self.worker.release_check(review['id'], old_token)
        self.assertEqual(self.worker.verification['token'], new_token)
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.callback(review, 'check-result', verification_token=old_token, matched=False).status_code, 409)
        self.assertEqual(self.worker.verification['token'], new_token)

    def test_malformed_assertion_urls_return_json_validation_error(self):
        review = self.draft()
        for url in ('https://www.google.com:bad/maps', 'https://www.google.com:99999/maps',
                    'https://[broken/maps', 'https://www.google.com/maps/' + 'a' * 2048):
            with self.subTest(url=url):
                response = self.callback(review, 'prepared', assertion=self.proof(review, url=url))
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.is_json)
                self.assertEqual(self.store.get(review['id'])['status'], 'preparing')
        self.assertEqual(self.callback(review, 'prepared', assertion=self.proof(review)).status_code, 200)

    def test_url_parser_normalizes_errors_for_every_caller(self):
        for url in (None, [], 'https://www.google.com:bad/maps', 'https://[broken/maps'):
            with self.subTest(url=url), self.assertRaises(ReviewError):
                maps_url(url)


if __name__ == '__main__':
    unittest.main()
