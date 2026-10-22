"""Real Qt async IO against a local synthetic HTTP server only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest

from PySide6.QtCore import QCoreApplication

from netease_music.client import Client
from netease_music.service import Request


class NeteaseClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                requests.append((self.path, body, self.headers))
                if self.path == '/slow':
                    time.sleep(.15)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/should-not-follow')
                    self.end_headers()
                    return
                code = {'/expired': 301, '/verification': 8821}.get(self.path, 200)
                payload = b'not-json' if self.path == '/bad' else json.dumps(dict(code=code)).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', 'external=must-not-be-replayed')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.client = Client()
        self.completed, self.failed = [], []
        self.client.completed.connect(lambda *values: self.completed.append(values))
        self.client.failed.connect(lambda *values: self.failed.append(values))

    def tearDown(self):
        self.client.cancel()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.app.processEvents()

    def operation(self, path, cookie=''):
        return (yield Request(self.base + path, dict(id='1'), cookie, True))

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), 'local async test did not finish')

    def test_post_cookie_is_not_in_url_and_jar_is_not_replayed(self):
        self.client.run('first', self.operation('/ok', 'test_cookie=not-real'))
        self.wait(lambda: len(self.completed) == 1)
        self.client.run('second', self.operation('/next'))
        self.wait(lambda: len(self.completed) == 2)
        self.assertNotIn('test_cookie', self.requests[0][0])
        self.assertIn(b'cookie=test_cookie%3Dnot-real', self.requests[0][1])
        self.assertIsNone(self.requests[1][2].get('Cookie'))
        self.assertNotIn(b'cookie=', self.requests[1][1])

    def test_redirect_and_malformed_json_fail_without_body_exposure(self):
        for path in ['/redirect', '/bad']:
            self.client.run(path, self.operation(path, 'test_cookie=not-real'))
            self.wait(lambda: len(self.failed) == (1 if path == '/redirect' else 2))
        self.assertEqual(self.completed, [])
        self.assertFalse(any(path == '/should-not-follow' for path, *_ in self.requests))
        self.assertFalse(any('test_cookie' in values[1] or 'not-json' in values[1] for values in self.failed))

    def test_auth_expiry_is_explicit(self):
        self.client.run('account', self.operation('/expired', 'test_cookie=not-real'))
        self.wait(lambda: bool(self.failed))
        self.assertIs(self.failed[0][2], True)

    def test_verification_is_not_session_expiry_or_automatic_retry(self):
        for kind in ('qr', 'qr_check'):
            before = len(self.failed)
            self.client.run(kind, self.operation('/verification', 'test_cookie=not-real'))
            self.wait(lambda: len(self.failed) == before + 1)
            self.assertIn('8821', self.failed[-1][1])
            self.assertIn('安全验证', self.failed[-1][1])
            self.assertIs(self.failed[-1][2], False)
            self.assertIsNone(self.client.operation)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.completed, [])

    def test_cancel_timeout_and_late_reply_do_not_complete_new_request(self):
        self.client.run('old', self.operation('/slow'))
        old = self.client.reply
        self.wait(lambda: bool(self.requests))
        self.client.cancel()
        self.client.run('new', self.operation('/ok'))
        self.client._read(old)
        self.client._finish(old)
        self.wait(lambda: bool(self.completed))
        self.assertEqual([entry[0] for entry in self.completed], ['new'])
        self.client.run('timeout', self.operation('/slow'))
        self.client.timer.timeout.emit()
        self.wait(lambda: bool(self.failed))
        self.assertEqual(self.failed[-1][0], 'timeout')
        self.assertEqual([entry[0] for entry in self.completed], ['new'])


if __name__ == '__main__':
    unittest.main()
