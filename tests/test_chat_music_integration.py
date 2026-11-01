"""Real Qt IPC/HTTP two-stage song choice against a loopback-only fake provider."""
import json
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests import test_music_ai_choice as fixtures
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from deskpet.chat.config import ProviderConfig
from deskpet.chat.window import ChatWindow


@contextmanager
def fake_provider():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            if len(requests) == 1:
                text = '[动作:music_local {"pattern":"流光"}][开心]这就选一个版本。'
            else:
                candidates = json.loads(request['messages'][-1]['content'])['candidates']
                selected = next(row for row in candidates if row['title'] == '流光现场')
                text = json.dumps({'id': selected['id']})
                # Keep request two alive while old reply deleteLater/finished work runs.
                time.sleep(.1)
            if request['stream']:
                pieces = [text[:len(text)//2], text[len(text)//2:]]
                body = ''.join('data: ' + json.dumps({'choices': [{'delta': {'content': part}}]})
                               + '\n\n' for part in pieces).encode() + b'data: [DONE]\n\n'
            else:
                body = json.dumps({'choices': [{'message': {'content': text}}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if request['stream'] else 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


class MusicHttpIntegrationTests(unittest.TestCase):
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def exercise_choice(self, stream):
        with fake_provider() as (url, requests), self.window() as (window, accessor):
            # Retain the isolated UI/music fixtures but use the real facade, QProcess
            # worker, Qt HTTP transport and local HTTP service for both requests.
            accessor.side_effect = lambda: ChatWindow.request_client(window)
            window.config = ProviderConfig(base_url=url, model='fake-local-model', stream=stream)
            client = window.request_client()
            completions, errors = [], []
            client.failed.connect(errors.append)
            client.completed.connect(lambda _: completions.append(
                (client.active, client.timer.isActive(), client.process.processId())))
            window.input.setPlainText('想听流光，选个现场版本吧')
            window.send_message()
            deadline = time.monotonic() + 15
            while window.pending and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertIsNone(window.pending, window.status.text())
            self.assertEqual(errors, [])
            self.assertEqual(len(requests), 2)
            self.assertEqual(len(completions), 2)
            # ChatWindow's first completed callback starts choice immediately.
            # Old cleanup must leave the new request/timer and worker intact.
            self.assertIsNotNone(completions[0][0])
            self.assertTrue(completions[0][1])
            self.assertIsNone(completions[1][0])
            self.assertFalse(completions[1][1])
            self.assertGreater(completions[0][2], 0)
            self.assertEqual(completions[0][2], completions[1][2])
            self.p.start_track.assert_called_once_with(1)
            QTest.qWait(120)
            self.p.start_track.assert_called_once_with(1)
            self.assertEqual(len(completions), 2)
            history = window.store.history(window.character)
            self.assertEqual(len(history), 2)
            self.assertIn('流光现场', history[-1]['content'])
            self.assertNotIn('"id"', history[-1]['content'])
            outbound = json.dumps(requests[1], ensure_ascii=False)
            self.assertNotIn(self.temp.name, outbound)
            self.assertNotIn('https://', outbound)

    def test_streamed_completion_can_start_choice_in_same_callback(self):
        self.exercise_choice(True)

    def test_json_completion_can_start_choice_in_same_callback(self):
        self.exercise_choice(False)


if __name__ == '__main__':
    unittest.main()
