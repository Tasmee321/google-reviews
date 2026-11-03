"""Local advisory checks preserve exact text and do not predict moderation outcomes."""
import tempfile
import unittest

from app import create_app
from review_policy import review_warnings
from review_store import validate_review


class ReviewPolicyTests(unittest.TestCase):
    def codes(self, text, **kwargs):
        return [item['code'] for item in review_warnings(text, **kwargs)]

    def test_flags_links_email_and_possible_phone_without_echoing_them(self):
        text = 'Contact private@example.com at +92 300 1234567, see https://example.com.'
        warnings = review_warnings(text)
        self.assertEqual(self.codes(text), ['website', 'email', 'possible_phone'])
        self.assertNotIn('private@example.com', str(warnings))
        self.assertNotIn('1234567', str(warnings))
        self.assertEqual(self.codes('WWW.example.com'), ['website'])

    def test_dates_ratings_prices_and_negative_feedback_are_not_flagged(self):
        for text in ('Visited 03-11-2026. Paid 2500 rupees. Rating 2/5.',
                     'Service was slow. I waited 40 minutes and the food was cold.',
                     'khana acha tha lekin service sust thi.', '', 'عملہ مددگار تھا۔'):
            with self.subTest(text=text):
                self.assertEqual(self.codes(text), [])

    def test_repetition_is_advisory_not_rewriting(self):
        self.assertEqual(self.codes('My experience.', repeated=True), ['repeated_text'])
        self.assertEqual(self.codes('', repeated=True), [])


class PreflightApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(self.directory.name)
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token': session['csrf']}
        self.store = self.app.extensions['review_store']

    def preflight(self, text):
        return self.client.post('/api/reviews/preflight', json={'text': text}, headers=self.headers)

    def test_preflight_does_not_store_or_connect_or_claim_approval(self):
        response = self.preflight('My own experience. https://example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['warnings'][0]['code'], 'website')
        self.assertEqual(self.store.count(), 0)
        self.assertEqual(self.app.extensions['review_worker'].snapshot()['status'], 'disconnected')
        self.assertIn('does not mean Google approved', self.preflight('Helpful staff.').json['message'])
        self.assertNotIn('score', response.json)

    def test_csrf_and_text_limits(self):
        self.assertEqual(self.client.post('/api/reviews/preflight', json={'text': 'Test'}).status_code, 403)
        for text in (None, [], 12, 'x' * 4001):
            self.assertEqual(self.preflight(text).status_code, 400)

    def test_checks_local_history_without_disclosing_accounts_or_retaining_deleted_text(self):
        text = 'MY actual\nexperience.'
        review = self.store.create(validate_review({'target': 'Market', 'expected_name': 'Market',
            'account_email': 'private@example.com', 'stars': 2, 'text': text}))
        self.assertEqual(self.preflight('my actual experience.').json['warnings'], [])
        for status in ('posted', 'unconfirmed', 'submitting'):
            self.store.update(review['id'], status=status)
            response = self.preflight('my actual experience.')
            self.assertEqual(response.json['warnings'][0]['code'], 'repeated_text')
            self.assertNotIn('private@example.com', response.text)
            self.assertEqual(self.store.get(review['id'])['text'], text)
        self.store.update(review['id'], status='posted')
        self.store.delete_history(review['id'])
        self.assertEqual(self.preflight('my actual experience.').json['warnings'], [])

    def test_guidance_uses_official_links_and_keeps_warnings_local(self):
        html = self.client.get('/').text
        for number in ('7400114', '10357321', '12648169'):
            self.assertIn('support.google.com/', html)
            self.assertIn(number, html)
        self.assertIn('No warnings ka matlab Google approval nahi', html)


if __name__ == '__main__':
    unittest.main()
