"""Exercise both chat transports without using a provider account."""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from deskpet.chat.client import ChatClient
from deskpet.chat.config import ConfigFile, ProviderConfig
from deskpet.chat.curl_request import CurlRequest, system_curl


class Connections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.release = threading.Event()
        cls.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers['Content-Length'])
                payload = json.loads(self.rfile.read(length))
                cls.requests.append((self.path, self.headers.get('Authorization'), payload))
                case = self.path.split('/')[1]
                if case in ('denied', 'redirect'):
                    self.send_response(401 if case == 'denied' else 307)
                    self.send_header('Location', '/should-not-be-requested')
                    self.end_headers()
                    return
                self.send_response(200)
                stream = payload['stream']
                self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
                if stream:
                    block = {'choices':[{'delta':{'content':'天依'}}]}
                    body = ('data: ' + json.dumps(block) + '\n\ndata: [DONE]\n\n').encode()
                    if case == 'held':
                        body = body.split(b'data: [DONE]')[0]
                else:
                    body = json.dumps({'choices':[{'message':{'content':'天依'}}]}).encode()
                    self.send_header('Content-Length', str(len(body) + (5 if case == 'truncated' else 0)))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                if case == 'truncated':
                    return
                # A relay can have delivered a full event while the socket remains open.
                cls.release.wait(8)

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.release.set()
        cls.server.shutdown()
        cls.server.server_close()

    def run_case(self, transport, case, test=False):
        config = ProviderConfig(f'http://127.0.0.1:{self.server.server_port}/{case}',
                                'fake-model', 'unit-key', transport=transport)
        client = ChatClient()
        results, errors, partial = [], [], []
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        client.completed.connect(results.append)
        client.failed.connect(errors.append)
        client.partial.connect(partial.append)
        client.completed.connect(loop.quit)
        client.failed.connect(loop.quit)
        text = '雪\n«t»\\"; url=file:///private'
        before = len(self.requests)
        client.start(config, [{'role':'user','content':text}], test=test)
        if transport == 'curl':
            self.assertIsInstance(client.reply, CurlRequest)
            self.assertEqual(client.reply.program, system_curl())
            arguments = client.reply.arguments
            self.assertEqual(arguments[0], '--disable')
            self.assertNotIn('unit-key', str(arguments))
            self.assertNotIn('private', str(arguments))
        timer.start(4500)
        if not results and not errors:
            loop.exec()
        timer.stop()
        client.cancel()
        if case == 'truncated':
            self.assertEqual(results, [])
            self.assertEqual(len(errors), 1)
        elif case in ('denied', 'redirect'):
            self.assertEqual(len(errors), 1)
            self.assertIn('401' if case == 'denied' else '307', errors[0])
        else:
            self.assertEqual(errors, [])
            self.assertEqual(results, ['天依'])
            self.assertEqual(bool(partial), not test)
        self.assertEqual(len(self.requests) - before, 1)
        _, key, payload = self.requests[-1]
        self.assertEqual(key, 'Bearer unit-key')
        self.assertEqual(payload['messages'][0]['content'], text)
        self.assertEqual(payload['stream'], not test)
        self.app.processEvents()

    def test_qt(self):
        for case, test in [('stream', False), ('json', True), ('denied', True), ('redirect', False), ('truncated', True)]:
            with self.subTest(case=case):
                self.run_case('qt', case, test)

    @unittest.skipUnless(os.name == 'nt', 'Windows built-in curl')
    def test_curl(self):
        for case, test in [('stream', False), ('json', True), ('denied', True), ('redirect', False), ('truncated', True)]:
            with self.subTest(case=case):
                self.run_case('curl', case, test)

    def test_cancel_and_timeout_during_open_event_stream(self):
        for transport in ('qt', 'curl') if os.name == 'nt' else ('qt',):
            for timeout in (False, True):
                with self.subTest(transport=transport, timeout=timeout):
                    config = ProviderConfig(f'http://127.0.0.1:{self.server.server_port}/held', 'm', transport=transport)
                    client = ChatClient()
                    loop = QEventLoop()
                    timer = QTimer()
                    timer.setSingleShot(True)
                    timer.timeout.connect(loop.quit)
                    outputs, errors, partials = [], [], []
                    client.completed.connect(outputs.append)
                    client.failed.connect(errors.append)
                    def stop_on_partial(text):
                        partials.append(text)
                        if timeout:
                            client.timer.timeout.emit()
                        else:
                            client.cancel()
                        loop.quit()
                    client.partial.connect(stop_on_partial)
                    client.start(config, [])
                    timer.start(4500)
                    loop.exec()
                    timer.stop()
                    self.app.processEvents()
                    self.assertEqual(partials, ['天依'])
                    self.assertEqual(outputs, [])
                    self.assertIsNone(client.reply)
                    self.assertEqual(bool(errors), timeout)
                    if timeout:
                        self.assertIn('HTTP 200', errors[0])

    def test_missing_system_curl_does_not_leave_an_active_request(self):
        config = ProviderConfig('https://example.test', 'm', transport='curl')
        client = ChatClient()
        errors = []
        client.failed.connect(errors.append)
        with patch('deskpet.chat.curl_request.system_curl', side_effect=ValueError('找不到系统 curl')):
            client.start(config, [])
        self.assertIsNone(client.reply)
        self.assertFalse(client.timer.isActive())
        self.assertEqual(errors, ['找不到系统 curl'])

    def test_config_bom_default_and_saved_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.json'
            path.write_text('{"base_url":"https://example.test","model":"test"}', encoding='utf-8-sig')
            store = ConfigFile(path)
            settings, warning = store.load()
            self.assertEqual(warning, '')
            self.assertEqual(settings.transport, 'qt')
            settings.transport = 'curl'
            store.save(settings)
            self.assertEqual(store.load()[0].transport, 'curl')
