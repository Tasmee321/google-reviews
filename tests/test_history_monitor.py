"""Local-only histories and verification assertions; no browser or real reviews."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import create_app
from review_store import ReviewError, ReviewStore, validate_review
from tests.test_review_store import payload


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ReviewStore(self.temp.name)

    def review(self, status='posted', **changes):
        review = self.store.create(validate_review(payload(**changes)))
        self.store.update(review['id'], status=status, business_key='place:fixture',
                          business_name='My Market', business_address='Main Road, Karachi',
                          business_url=review['navigation_url'])
        return self.store.get(review['id'])

    def test_delete_removes_payload_but_preserves_counts_and_duplicate_guard(self):
        review = self.review()
        before = self.store.business_statistics()
        self.assertEqual(self.store.delete_history(review['id']), 1)
        self.assertEqual(self.store.list_reviews(), [])
        self.assertEqual(self.store.business_statistics(), before)
        self.assertTrue(self.store.duplicate('new', 'place:fixture', 'owner@example.com'))
        self.assertFalse(self.store.duplicate('new', 'place:fixture', 'other@example.com'))
        with self.store.connect() as db:
            receipt = dict(db.execute('SELECT * FROM receipts').fetchone())
        self.assertNotIn('text', receipt)
        self.assertNotIn('account_email', receipt)
        self.assertNotIn('owner@example.com', str(receipt))
        self.assertEqual(len(receipt['account_hash']), 64)
        reopened = ReviewStore(self.temp.name)
        self.assertTrue(reopened.duplicate('new', 'place:fixture', 'owner@example.com'))

    def test_active_delete_and_clear_are_atomic(self):
        old = self.review()
        active = self.review(status='ready')
        for identifier in (active['id'], None):
            with self.assertRaises(ReviewError):
                self.store.delete_history(identifier)
        self.assertEqual(self.store.count(), 2)
        self.assertEqual(self.store.get(old['id'])['status'], 'posted')

    def test_pending_counts_and_failed_payloads(self):
        self.review('unconfirmed')
        self.review('failed')
        self.store.delete_history()
        self.assertEqual(self.store.business_statistics()[0]['pending'], 1)
        self.assertEqual(self.store.business_statistics()[0]['posted'], 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0], 1)

    def test_failed_check_never_claims_deletion_or_public_live(self):
        review = self.review()
        self.store.record_saved_check(review['id'], False, 'Not verified')
        saved = self.store.get(review['id'])
        self.assertEqual(saved['status'], 'posted')
        self.assertEqual(saved['saved_status'], 'unverified')
        self.assertNotIn('public_status', saved)
        self.assertTrue(saved['checked_at'])

    def test_saved_check_reconciles_only_uncertainty(self):
        review = self.review('unconfirmed')
        self.store.record_saved_check(review['id'], True, 'Saved only', 'fixture-id')
        saved = self.store.get(review['id'])
        self.assertEqual(saved['status'], 'posted')
        self.assertEqual(saved['saved_review_id'], 'fixture-id')
        self.assertEqual(saved['saved_status'], 'verified')

    def test_account_shortcuts_are_not_credentials(self):
        self.store.remember_account('OWNER@EXAMPLE.COM')
        self.store.remember_account('other@example.com')
        self.assertEqual(len(self.store.accounts()), 2)
        self.assertEqual(set(self.store.accounts()[0]), {'email', 'verified_at'})
        self.store.forget_account('owner@example.com')
        self.assertEqual(len(self.store.accounts()), 1)

    def test_monitor_candidate_includes_old_history_and_rate_limits(self):
        review = self.review()
        with self.store.connect() as db:
            db.execute('UPDATE reviews SET updated_at=? WHERE id=?',
                       ((datetime.now(timezone.utc)-timedelta(days=7)).isoformat(), review['id']))
        self.assertEqual(self.store.check_candidate('owner@example.com')['id'], review['id'])
        self.assertIsNone(self.store.check_candidate('other@example.com'))
        self.store.claim_auto_check(review['id'])
        with self.assertRaises(ReviewError):
            self.store.claim_auto_check(review['id'])
        self.store.record_saved_check(review['id'], True, 'Saved only', 'fixture')
        self.assertIsNone(self.store.check_candidate('owner@example.com'))


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict('os.environ', {'REVIEW_BROWSER':'chrome'}):
            self.app = create_app(self.temp.name, config={"mode": "extension", "network_guard": {"enabled": False}})
        self.client = self.app.test_client()
        self.assertEqual(self.client.post('/api/unlock', json={'token': self.app.extensions['dashboard_token']}).status_code, 200)
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.headers = {'X-CSRF-Token':session['csrf']}
        self.store = self.app.extensions['review_store']
        self.worker = self.app.extensions['review_worker']
        self.worker.connect({'email':'owner@example.com'})
        review = self.store.create(validate_review(payload()))
        self.store.update(review['id'], status='unconfirmed', business_key='place:fixture',
                          business_url='https://www.google.com/maps/place/My+Market/data=!1sfixture')
        self.review = self.store.get(review['id'])
        self.base = '/api/reviews/'+review['id']
        self.token = {'confirmation_token':self.review['confirmation_token']}

    def post(self, suffix, data):
        return self.client.post(self.base+suffix, json=data, headers=self.headers)

    def test_delete_requires_csrf_confirmation_and_preserves_guard(self):
        self.assertEqual(self.client.post(self.base+'/delete',json={'confirm_local_delete':True}).status_code,403)
        self.assertEqual(self.post('/delete',{}).status_code,400)
        self.assertEqual(self.post('/delete',{'confirm_local_delete':True}).status_code,200)
        self.assertEqual(self.client.get(self.base).status_code,404)
        self.assertTrue(self.store.duplicate('new','place:fixture','owner@example.com'))

    def test_check_reservation_blocks_posting_switches_and_deletes(self):
        response = self.post('/check-start',self.token)
        self.assertEqual(response.status_code,200)
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.post('/check-start',self.token).status_code,409)
        self.assertEqual(self.post('/delete',{'confirm_local_delete':True}).status_code,409)
        self.assertEqual(self.client.post('/api/browser/select',json={'email':'owner@example.com'},headers=self.headers).status_code,409)
        self.assertEqual(self.post('/check-result',{**self.token,'verification_token':'wrong','matched':False}).status_code,409)
        self.assertTrue(self.worker.snapshot()['busy'])
        self.assertEqual(self.post('/check-result',{**self.token,'verification_token':response.json['verification_token'],'matched':False}).status_code,200)
        self.assertFalse(self.worker.snapshot()['busy'])
        self.assertEqual(self.store.get(self.review['id'])['status'],'unconfirmed')
        self.assertEqual(self.post('/check-start',self.token).status_code,429)

    def test_positive_proof_requires_exact_account_business_rating_and_text(self):
        reserved = self.post('/check-start',self.token).json
        proof = {'name':self.review['expected_name'],'email':self.review['account_email'],
                 'url':self.review['business_url'],'text':self.review['text'],
                 'stars':self.review['stars'],'saved_review_id':'fixture-saved'}
        response = self.post('/check-result',{**self.token,'verification_token':reserved['verification_token'],
                            'matched':True,'assertion':proof})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['review']['status'],'posted')
        self.assertEqual(response.json['review']['saved_status'],'verified')
        self.assertEqual(self.post('/publish',self.token).status_code,409)

    def test_invalid_proof_releases_lock_without_success(self):
        reserved = self.post('/check-start',self.token).json
        self.assertEqual(self.post('/check-result',{**self.token,'verification_token':reserved['verification_token'],
                            'matched':True,'assertion':{'saved_review_id':'fixture'}}).status_code,409)
        self.assertFalse(self.worker.snapshot()['busy'])
        self.assertEqual(self.store.get(self.review['id'])['status'],'unconfirmed')

    def test_expired_check_does_not_leave_browser_busy(self):
        self.post('/check-start',self.token)
        self.worker.verification['expires'] = 0
        self.assertFalse(self.worker.snapshot()['busy'])
        self.assertIsNone(self.worker.verification)

    def test_history_offset_validation(self):
        for offset in ('-1','100001','x'):
            self.assertEqual(self.client.get('/api/history?offset='+offset).status_code,400)
        response = self.client.get('/api/history?offset=40')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['reviews'],[])
        self.assertEqual(response.json['total'],1)

    def test_shortcut_selection_rejects_unknown_and_verifies_identity(self):
        self.assertEqual(self.client.post('/api/browser/select',json={'email':'other@example.com'},headers=self.headers).status_code,400)
        self.store.remember_account('other@example.com')
        response=self.client.post('/api/browser/select',json={'email':'other@example.com'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/api/browser/verified',json={'email':'owner@example.com'},headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/browser/verified',json={'email':'other@example.com'},headers=self.headers).status_code,200)
        self.assertEqual(self.worker.snapshot()['email'],'other@example.com')


if __name__=='__main__':
    unittest.main()
