"""Local advisory checks preserve exact text and do not predict moderation outcomes."""
import tempfile
import unittest

from app import create_app
from review_policy import policy_submission_check, review_warnings
from review_store import ReviewError, validate_review


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

    def test_other_account_history_warning_is_fixed_and_does_not_claim_manipulation(self):
        warnings = review_warnings('Private draft example.', cross_account=True)
        self.assertEqual(self.codes('My experience.', cross_account=True), ['cross_account_business'])
        self.assertNotIn('Private draft example.', str(warnings))
        self.assertIn('submitted or uncertain', warnings[0]['message'])
        self.assertEqual(self.codes('My experience.', repeated=True, cross_account=True),
                         ['repeated_text', 'cross_account_business'])


class PolicySubmissionTests(unittest.TestCase):
    def test_exact_boolean_confirmation_is_required(self):
        for value in (None, False, 0, 1, 'true', 'false', [], {}, [True]):
            with self.subTest(value=value), self.assertRaises(ReviewError) as caught:
                policy_submission_check({'policy_confirmed': value}, 'My experience.')
            self.assertEqual(caught.exception.status, 400)
            self.assertIn('policy_confirmed', caught.exception.fields)
        for data in ({}, None, [], 'true'):
            with self.subTest(data=data), self.assertRaises(ReviewError):
                policy_submission_check(data, 'My experience.')

    def test_confirmation_explains_self_attestation_without_claiming_approval(self):
        with self.assertRaises(ReviewError) as caught:
            policy_submission_check({}, 'My experience.')
        message = str(caught.exception)
        for phrase in ('firsthand', 'branch and account', 'incentives', 'conflict of interest',
                       'multiple-account', 'private information', 'advertising', 'off-topic',
                       'harassment', "not Google's approval"):
            self.assertIn(phrase, message)

    def test_clear_links_and_emails_block_without_echoing_private_values(self):
        examples = ('See https://example.com/private.', 'WWW.example.com',
                    'Email private@example.com for details.')
        for text in examples:
            with self.subTest(text=text), self.assertRaises(ReviewError) as caught:
                policy_submission_check({'policy_confirmed': True}, text)
            self.assertIn('text', caught.exception.fields)
            self.assertNotIn(text, str(caught.exception))
            self.assertNotIn('private@example.com', str(caught.exception))
            self.assertIn('prepare the review again', str(caught.exception))

    def test_advisories_do_not_block_or_rewrite_exact_text(self):
        text = 'My own experience.\nThe queue took 40 minutes. Ref 12345678901.'
        data = {'policy_confirmed': True, 'text': text, 'stars': 2}
        before = dict(data)
        self.assertIsNone(policy_submission_check(data, text, repeated=True, cross_account=True))
        self.assertEqual(data, before)
        self.assertEqual(data['text'], text)
        self.assertEqual(data['stars'], 2)

    def test_respectful_negative_and_multilingual_reviews_pass(self):
        for text in ('Service was slow. I waited 40 minutes and the food was cold.',
                     'khana acha tha lekin service sust thi.', 'عملہ مددگار تھا۔',
                     'Visited 03-11-2026. Paid 2500 rupees. Rating 2/5.'):
            with self.subTest(text=text):
                self.assertIsNone(policy_submission_check({'policy_confirmed': True}, text))

    def test_malformed_or_overlong_text_fails_with_a_fixed_message(self):
        for text in (None, [], 12, '', ' \n ', 'x' * 4001):
            with self.subTest(text=text), self.assertRaises(ReviewError) as caught:
                policy_submission_check({'policy_confirmed': True}, text)
            self.assertEqual(caught.exception.fields, {'text': 'Enter a review of 1 to 4,000 characters.'})
        self.assertIsNone(policy_submission_check({'policy_confirmed': True}, 'x' * 4000))


class PreflightApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(self.directory.name)
        self.client = self.app.test_client()
        self.assertEqual(self.client.post('/api/unlock', json={'token': self.app.extensions['dashboard_token']}).status_code, 200)
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
