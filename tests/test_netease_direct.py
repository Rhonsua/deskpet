"""Default NetEase direct login with fake cookies; no user login or QR scan."""
import json
import base64
import time
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest, QSslSocket

from netease_music.client import Client
from netease_music.direct import cookie_header, cookie_values, qr_url, request_values, response_cookie, validate_url, prepare_request
from netease_music.service import ApiError, Request, Service, SessionExpired
from netease_music.storage import Cache, session_data
from tests.test_netease_music import drive


DIRECT = dict(api='', uid='77', nickname='直连测试用户', cookie='MUSIC_U=fake-login-token; __csrf=fake-csrf')


class NeteaseDirectTests(unittest.TestCase):
    def test_weapi_login_only_routes_and_roundtrip(self):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        for path in ('login/qrcode/unikey', 'login/qrcode/client/login', 'w/nuser/account/get'):
            with self.subTest(path=path), patch('netease_music.direct.secrets.choice', return_value='a'):
                address, wire, cookie = prepare_request('https://music.163.com/api/' + path,
                                                       dict(type=3, key='fake-key'), DIRECT['cookie'])
                self.assertEqual(address, 'https://music.163.com/weapi/' + path)
                self.assertEqual(set(wire), {'params', 'encSecKey'})
                self.assertEqual(len(wire['encSecKey']), 256)
                first = unpad(AES.new(b'a'*16, AES.MODE_CBC, b'0102030405060708').decrypt(base64.b64decode(wire['params'])), 16)
                plain = unpad(AES.new(b'0CoJUm6Qyw8W8jud', AES.MODE_CBC, b'0102030405060708').decrypt(base64.b64decode(first)), 16)
                payload = json.loads(plain)
                self.assertEqual(payload['csrf_token'], 'fake-csrf')
                self.assertEqual(payload['key'], 'fake-key')
                self.assertEqual(payload['type'], 1 if path.startswith('login/') else 3)
                self.assertEqual(cookie, DIRECT['cookie'])
                self.assertNotIn('fake-login-token', str(wire))
        address, values, _ = prepare_request('https://music.163.com/api/song/lyric', {'id': '1'}, '')
        self.assertEqual(address, 'https://music.163.com/api/song/lyric')
        self.assertEqual(values, dict(id='1', csrf_token=''))

    def test_anonymous_key_uses_official_origin_and_local_qr_url(self):
        def respond(request):
            self.assertTrue(request.direct)
            self.assertFalse(request.community)
            self.assertEqual(request.params, dict(type=3))
            self.assertEqual(request.cookie, '')
            self.assertEqual(request.url, 'https://music.163.com/api/login/qrcode/unikey')
            return dict(code=200, unikey='fake-key-123')
        result = drive(Service().qr(), respond)
        self.assertEqual(result, dict(key='fake-key-123', url='https://music.163.com/login?codekey=fake-key-123'))

    def test_wait_expired_and_confirmed_profile_are_distinct(self):
        for code in (800, 801, 802):
            result = drive(Service().check_qr('fake-key-123'), lambda request: dict(code=code))
            self.assertEqual(result, dict(code=code))
        requests = []
        def confirmed(request):
            requests.append(request)
            self.assertTrue(request.direct)
            if request.url.endswith('/client/login'):
                self.assertEqual(request.params, dict(key='fake-key-123', type=3))
                self.assertEqual(request.cookie, '')
                return dict(code=803, _direct_cookie=DIRECT['cookie'])
            self.assertEqual(request.cookie, DIRECT['cookie'])
            self.assertEqual(request.url, 'https://music.163.com/api/w/nuser/account/get')
            return dict(code=200, profile=dict(userId=77, nickname=DIRECT['nickname']))
        result = drive(Service().check_qr('fake-key-123'), confirmed)
        self.assertEqual(result['session'], DIRECT)
        self.assertNotIn('fake-login-token', repr(requests[-1]))
        with self.assertRaises(ApiError):
            drive(Service().check_qr('fake-key-123'), lambda request: dict(code=803))

    def test_confirm_without_logged_in_profile_does_not_create_session(self):
        def respond(request):
            if request.url.endswith('/client/login'):
                return dict(code=803, _direct_cookie=DIRECT['cookie'])
            return dict(code=200, profile=None, account=None)
        with self.assertRaises(SessionExpired):
            drive(Service().check_qr('fake-key-123'), respond)
        with self.assertRaises(ValueError):
            session_data(dict(DIRECT, cookie='MUSIC_A=anonymous'), '')

    def test_direct_personal_requests_keep_cookie_only_on_allowlisted_origin(self):
        service = Service('', DIRECT)
        for path, expected in [('/user/playlist', '/api/user/playlist'), ('/likelist', '/api/song/like/get'),
                               ('/playlist/detail', '/api/v6/playlist/detail')]:
            request = service.request(path, dict(id='1'))
            self.assertTrue(request.direct)
            self.assertEqual(request.url, 'https://music.163.com' + expected)
            values, cookie = request_values(request.url, request.params, request.cookie)
            self.assertNotIn('cookie', values)
            self.assertEqual(values['csrf_token'], 'fake-csrf')
            self.assertEqual(cookie, DIRECT['cookie'])
        for url in ['http://music.163.com/api/user/playlist', 'https://music.163.com.evil.test/api/user/playlist',
                    'https://evil.test/api/user/playlist', 'https://music.163.com/api/logout',
                    'https://music.163.com/api/user/playlist?cookie=bad',
                    'https://music.163.com:999/api/user/playlist', 'https://a:b@music.163.com/api/user/playlist']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                request_values(url, {}, DIRECT['cookie'])

    def test_response_cookie_whitelist_domains_attributes_and_removal(self):
        cookies = response_cookie('', [b'MUSIC_U=fake-token; Domain=.music.163.com; Path=/; HttpOnly; Secure',
            b'__csrf=test-csrf; Path=/', b'other_tracking=ignore; Path=/',
            b'MUSIC_U=bad; Domain=evil.test; Path=/', b'__csrf=bad; Path=/unrelated',
            b'MUSIC_U=bad\r\nInjected=yes'])
        self.assertEqual(cookie_values(cookies), dict(MUSIC_U='fake-token', __csrf='test-csrf'))
        self.assertNotIn('Domain', cookies)
        self.assertNotIn('HttpOnly', cookies)
        self.assertNotIn('tracking', cookies)
        self.assertEqual(response_cookie(cookies, [b'MUSIC_U=; Max-Age=0; Path=/']), '__csrf=test-csrf')
        with self.assertRaises(ValueError):
            cookie_header('MUSIC_U=bad\r\nInjected=yes')
        with self.assertRaises(ValueError):
            qr_url('bad&redirect=https://evil.test')

    def test_direct_session_dpapi_and_cross_origin_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Cache(Path(directory))
            cache.save_session(DIRECT)
            self.assertNotIn('fake-login-token', cache.path('session.json').read_text())
            self.assertEqual(cache.load_session(''), (DIRECT, ''))
            self.assertIsNone(cache.load_session('https://api.example.test')[0])
            with self.assertRaises(ValueError):
                Service('https://api.example.test', DIRECT)
            cache.clear_private()
            self.assertIsNone(cache.load_session('')[0])


class NeteaseDirectTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native TLS')
    def test_windows_client_uses_native_tls_without_disabling_verification(self):
        client = Client()
        self.addCleanup(client.cancel)
        self.assertEqual(QSslSocket.activeBackend(), 'schannel')

    def test_official_set_cookie_enters_payload_not_cookie_jar(self):
        client = Client()
        self.addCleanup(client.cancel)
        captured = []
        operation = (value for value in ())
        client.operation = operation
        client.descriptor = Request('https://music.163.com/api/login/qrcode/client/login', {}, direct=True, allowed=(803,))
        reply = Mock()
        reply.readAll.return_value = b'{"code":803}'
        reply.attribute.return_value = 200
        reply.error.return_value = QNetworkReply.NetworkError.NoError
        reply.url.return_value = QUrl(client.descriptor.url)
        reply.rawHeaderPairs.return_value = [(b'Set-Cookie', b'MUSIC_U=fake-token; Domain=.music.163.com; Path=/')]
        client.reply = reply
        client.raw = bytearray()
        client._advance = lambda value=None, error=None: captured.append((value, error))
        client._finish(reply)
        self.assertEqual(captured[0][0]['_direct_cookie'], 'MUSIC_U=fake-token')
        self.assertEqual(client.manager.cookieJar().cookiesForUrl(QUrl('https://music.163.com')), [])

    def test_client_posts_encrypted_account_to_weapi(self):
        client = Client()
        reply = Mock()
        manager = Mock()
        manager.post.return_value = reply
        client.manager = manager
        client.deadline = time.monotonic() + 60
        client._request(Request('https://music.163.com/api/w/nuser/account/get', {}, DIRECT['cookie'], direct=True))
        request, body = manager.post.call_args.args
        self.assertEqual(request.url().toString(), 'https://music.163.com/weapi/w/nuser/account/get')
        self.assertTrue(body.startswith(b'params='))
        self.assertIn(b'encSecKey=', body)
        self.assertNotIn(b'fake-login-token', body)
        self.assertEqual(bytes(request.rawHeader('Cookie')).decode(), DIRECT['cookie'])
        client.cancel()

    def test_direct_nonofficial_request_is_rejected_before_network(self):
        client = Client()
        self.addCleanup(client.cancel)
        failures = []
        client.failed.connect(lambda *values: failures.append(values))
        def operation():
            yield Request('https://evil.test/api/user/playlist', {}, DIRECT['cookie'], direct=True)
        client.run('unsafe', operation())
        self.assertIsNone(client.reply)
        self.assertEqual(len(failures), 1)
        self.assertNotIn('fake-login-token', failures[0][1])


if __name__ == '__main__':
    unittest.main()
