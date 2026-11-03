"""Offline UK country checks: strict responses, freshness, fail-closed and redaction."""
import unittest
from unittest.mock import MagicMock

from app_config import ConfigError, validate_config
from diagnostics import Diagnostics, diagnostic_report
from network_guard import TRACE_URLS, UKNetworkGuard, parse_trace
from review_store import ReviewError


class NetworkGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.guard = UKNetworkGuard(validate_config({})['network_guard'], clock=lambda: self.now)
        self.context = MagicMock()
        self.page = self.context.new_page.return_value
        response = MagicMock(status=200, headers={'content-type': 'text/plain; charset=utf-8'})
        def navigate(url, **kwargs):
            self.page.url = url
            return response
        self.page.goto.side_effect = navigate
        self.page.evaluate.return_value = 'ip=1.1.1.1\nloc=GB\n'

    def test_safe_defaults_and_strict_config(self):
        self.assertFalse(validate_config({})['city_geolocation'])
        self.assertTrue(validate_config({})['network_guard']['enabled'])
        for guard in ({'enabled': 1}, {'interval_seconds': 0}, {'timeout_ms': True}, {'fallback': True}):
            with self.assertRaises(ConfigError):
                validate_config({'network_guard': guard})

    def test_both_browser_probes_must_confirm_uk_without_retaining_ip(self):
        result = self.guard.check(self.context)
        self.assertTrue(result['allowed'])
        self.assertEqual(result['country'], 'GB')
        self.assertEqual(result['address_families'], [4])
        self.assertEqual(self.page.goto.call_count, len(TRACE_URLS))
        self.context.request.get.assert_not_called()
        self.assertNotIn('1.1.1.1', str(result))
        self.page.close.assert_called_once()

    def test_freshness_and_forced_recheck(self):
        self.guard.check(self.context)
        self.guard.check(self.context)
        self.assertEqual(self.page.goto.call_count, 2)
        self.guard.check(self.context, force=True)
        self.assertEqual(self.page.goto.call_count, 4)
        self.now += 31
        self.assertFalse(self.guard.snapshot()['allowed'])
        self.assertEqual(self.guard.snapshot()['status'], 'stale')
        self.guard.check(self.context)
        self.assertTrue(self.guard.snapshot()['allowed'])

    def test_non_uk_second_endpoint_does_not_fall_back_to_first_success(self):
        self.page.evaluate.side_effect = ['ip=1.1.1.1\nloc=GB', 'ip=8.8.8.8\nloc=US']
        with self.assertRaisesRegex(ReviewError, 'not UK'):
            self.guard.check(self.context)
        self.assertFalse(self.guard.snapshot()['allowed'])
        self.assertEqual(self.guard.snapshot()['code'], 'not_uk')

    def test_error_revokes_prior_success_and_redacts_external_exception(self):
        self.guard.check(self.context)
        self.page.goto.side_effect = RuntimeError('cookie=secret; private@example.com; 8.8.8.8')
        with self.assertRaises(ReviewError) as caught:
            self.guard.check(self.context, force=True)
        self.assertFalse(self.guard.snapshot()['allowed'])
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('private@example.com', str(self.guard.snapshot()))

    def test_redirect_is_not_accepted(self):
        self.page.goto.side_effect = lambda *args, **kwargs: MagicMock(status=200)
        self.page.url = 'https://different.example/trace'
        with self.assertRaises(ReviewError):
            self.guard.check(self.context)

    def test_malformed_private_duplicate_and_oversized_responses_fail(self):
        for text in ('loc=GB', 'ip=192.168.1.1\nloc=GB', 'ip=1.1.1.1\nloc=GB\nloc=US',
                     'ip=1.1.1.1\nloc=UK', 'ip=1.1.1.1\nloc=gb', 'x' * 4097):
            if text.endswith('loc=UK'):
                self.page.evaluate.return_value = text
                with self.assertRaises(ReviewError):
                    self.guard.check(self.context, force=True)
            else:
                with self.assertRaises(ValueError):
                    parse_trace(text)

    def test_ipv6_is_reported_without_claiming_all_routes(self):
        self.page.evaluate.side_effect = ['ip=2606:4700:4700::1111\nloc=GB', 'ip=1.1.1.1\nloc=GB']
        self.assertEqual(self.guard.check(self.context)['address_families'], [4, 6])

    def test_disabled_mode_is_explicit_and_does_not_probe(self):
        guard = UKNetworkGuard(validate_config({'network_guard': {'enabled': False}})['network_guard'])
        self.assertEqual(guard.check(self.context)['status'], 'disabled')
        self.context.new_page.assert_not_called()


class DiagnosticTests(unittest.TestCase):
    def test_export_is_allowlisted_not_a_dump_of_browser_state(self):
        diagnostics = Diagnostics()
        diagnostics.record('network_blocked')
        browser = {'status': 'disconnected', 'email': 'private@example.com', 'message': 'SECRET',
                   'cookies': 'SECRET', 'network': {'status': 'blocked', 'ip': '8.8.8.8', 'message': 'SECRET'}}
        report = diagnostic_report(validate_config({}), browser, {'status': 'protected', 'path': 'SECRET'}, diagnostics)
        for forbidden in ('SECRET', 'private@example.com', '8.8.8.8'):
            self.assertNotIn(forbidden, str(report))
        self.assertIn('network_blocked', str(report))

    def test_events_are_bounded_and_reject_raw_errors(self):
        diagnostics = Diagnostics()
        for _ in range(80):
            diagnostics.record('browser_action_failed', 'login')
        self.assertEqual(len(diagnostics.events()), 50)
        with self.assertRaises(ValueError):
            diagnostics.record('password=secret')


if __name__ == '__main__':
    unittest.main()
