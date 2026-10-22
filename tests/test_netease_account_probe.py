import json
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from netease_music.account_probe import AccountProbe, NoRedirect, verify_browser_cookie


class AccountProbeTests(unittest.TestCase):
    def response(self, body):
        response = Mock(status=200)
        response.read.return_value = json.dumps(body).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    @patch('netease_music.account_probe.build_opener')
    def test_verifies_encrypted_fixed_origin_with_current_cookie(self, opener):
        opener.return_value.open.return_value = self.response(
            dict(code=200, profile=dict(userId=77, nickname='测试账号')))
        profile, stage = verify_browser_cookie('MUSIC_U=synthetic-only; __csrf=fake-csrf')
        self.assertEqual(profile, dict(userId='77', nickname='测试账号'))
        self.assertEqual(stage, 'verified')
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://music.163.com/weapi/w/nuser/account/get')
        self.assertIn('MUSIC_U=synthetic-only', request.get_header('Cookie'))
        self.assertNotIn(b'synthetic-only', request.data)
        self.assertIn(b'encSecKey=', request.data)
        self.assertEqual(opener.return_value.open.call_args.kwargs, dict(timeout=8))
        self.assertIsInstance(opener.call_args.args[0], NoRedirect)

    @patch('netease_music.account_probe.build_opener')
    def test_empty_rejected_and_malformed_are_not_logins(self, opener):
        for body, stage in [
            ({'code': 200, 'profile': None}, 'verification_session'),
            ({'code': 301}, 'verification_session'),
            ({'code': 8821}, 'verification_rejected'),
            ({'code': 200, 'profile': {'userId': 0}}, 'verification_response'),
            ({'code': 200, 'profile': {'userId': '１２'}}, 'verification_response'),
            ([], 'verification_response'),
        ]:
            with self.subTest(body=body):
                opener.return_value.open.return_value = self.response(body)
                self.assertEqual(verify_browser_cookie('MUSIC_U=synthetic-only'), (None, stage))

    @patch('netease_music.account_probe.build_opener')
    def test_network_errors_do_not_expose_raw_details(self, opener):
        for error, stage in [(URLError('secret'), 'verification_network'),
                             (HTTPError('secret', 403, 'secret', {}, None), 'verification_rejected')]:
            opener.return_value.open.side_effect = error
            self.assertEqual(verify_browser_cookie('MUSIC_U=synthetic-only'), (None, stage))
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_background_result_cannot_pair_previous_account_with_new_cookie(self):
        release = threading.Event()
        started = threading.Event()
        def verify(cookie):
            started.set()
            release.wait(3)
            return dict(userId='77'), 'verified'
        probe = AccountProbe(verify)
        self.assertEqual(probe.poll('MUSIC_U=old'), (None, 'verification_native'))
        self.assertTrue(started.wait(1))
        self.assertEqual(probe.poll('MUSIC_U=new'), (None, None))
        release.set()
        result = probe.results.get(timeout=3)
        probe.results.put(result)
        self.assertEqual(probe.poll('MUSIC_U=new'), (None, 'verification_native'))
        result = probe.results.get(timeout=3)
        probe.results.put(result)
        self.assertEqual(probe.poll('MUSIC_U=new'), (dict(userId='77'), 'verified'))

    def test_retry_interval_and_manual_retry(self):
        probe = AccountProbe(lambda cookie: (None, 'verification_session'))
        probe.poll('MUSIC_U=test')
        result = probe.results.get(timeout=3)
        probe.results.put(result)
        self.assertEqual(probe.poll('MUSIC_U=test'), (None, 'verification_session'))
        self.assertEqual(probe.poll('MUSIC_U=test'), (None, None))
        self.assertEqual(probe.poll('MUSIC_U=test', retry=True), (None, 'verification_native'))


if __name__ == '__main__':
    unittest.main()
