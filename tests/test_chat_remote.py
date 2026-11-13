"""IPC framing, cancellation and error cleanup without accessing any API."""
import io
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication
from deskpet.chat.remote import ChatClient
from deskpet.chat.config import ProviderConfig


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.client = ChatClient()
        self.client.process = Mock()
        self.client.process.readAllStandardOutput.return_value = b''
        self.client.active = 2
        self.client.ready = True
        self.client.timer.start(90000)
        self.results, self.errors, self.partials = [], [], []
        self.client.completed.connect(self.results.append)
        self.client.failed.connect(self.errors.append)
        self.client.partial.connect(self.partials.append)

    def tearDown(self):
        self.client.timer.stop()
        self.client.closed = True
        self.client.deleteLater()

    def feed(self, payload):
        self.client.process.readAllStandardOutput.return_value = payload
        self.client._read()

    def event(self, kind, text, request=2):
        return ('TIANYI_CHAT '+json.dumps(dict(type=kind, id=request, text=text),
                                         ensure_ascii=False)+'\n').encode()

    def test_utf8_split_and_late_completed_messages(self):
        message = self.event('partial', '天依在呢')
        cut = message.index('天'.encode())+1
        self.feed(message[:cut])
        self.assertEqual(self.partials, [])
        self.feed(message[cut:]+self.event('completed', 'old', request=1))
        self.assertEqual(self.partials, ['天依在呢'])
        self.assertEqual(self.results, [])
        self.feed(self.event('completed', 'new')*2)
        self.assertEqual(self.results, ['new'])
        self.assertFalse(self.client.timer.isActive())

    def test_cancel_and_timeout_ignore_late_events(self):
        self.client.pending = {'secret': 'not persisted'}
        self.client.timer.timeout.emit()
        self.assertEqual(len(self.errors), 1)
        self.assertIsNone(self.client.pending)
        self.assertIsNone(self.client.active)
        self.feed(self.event('partial', 'late')+self.event('completed', 'late'))
        self.assertEqual(self.partials, [])
        self.assertEqual(self.results, [])
        self.client.process.waitForFinished.assert_not_called()

    def test_failed_start_clears_queued_secret_and_reports_once(self):
        self.client.ready = False
        self.client.pending = {'config': {'api_key': 'fake'}}
        self.client._process_error(QProcess.ProcessError.FailedToStart)
        self.client._exited()
        self.assertEqual(len(self.errors), 1)
        self.assertIsNone(self.client.pending)
        self.assertIsNone(self.client.active)
        self.assertFalse(self.client.timer.isActive())

    def test_frozen_worker_pipe_ignores_legacy_windows_text_encoding(self):
        from deskpet.chat.player_worker import emit
        raw = io.BytesIO()
        with io.TextIOWrapper(raw, encoding='gbk') as stdio, patch('sys.stdout', stdio):
            emit(dict(type='completed', id=2, text='连接成功 🎵'))
            self.feed(raw.getvalue())
        self.assertEqual(self.results, ['连接成功 🎵'])
        self.assertFalse(self.client.timer.isActive())

    def test_bad_legacy_worker_encoding_reports_immediately(self):
        self.feed(b'TIANYI_CHAT ' + json.dumps(dict(type='completed', id=2, text='连接成功'),
                  ensure_ascii=False).encode('gbk') + b'\n')
        self.assertFalse(self.client.timer.isActive())
        self.assertEqual(len(self.errors), 1)
        self.assertIn('解码', self.errors[0])


class WorkerRoundTripTests(unittest.TestCase):
    def test_local_relay_and_actual_worker_return_unicode_to_ui(self):
        app = QApplication.instance() or QApplication([])
        reply = '天依收到了 🎵'
        received = []

        class Relay(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                stream = request['stream']
                received.append(stream)
                if stream:
                    data = json.dumps({'choices':[{'delta':{'content':reply}}]}, ensure_ascii=False)
                    body = ('data: ' + data + '\n\ndata: [DONE]\n\n').encode('utf-8')
                else:
                    body = json.dumps({'choices':[{'message':{'content':reply}}]},
                                      ensure_ascii=False).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Relay) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            client = ChatClient()
            loop = QEventLoop()
            replies, errors = [], []
            client.completed.connect(replies.append)
            client.failed.connect(errors.append)
            client.completed.connect(loop.quit)
            client.failed.connect(loop.quit)
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            try:
                cfg = ProviderConfig(base_url=f'http://127.0.0.1:{server.server_port}/v1', model='local-test')
                for test_connection in (True, False):
                    client.start(cfg, [{'role':'user','content':'你好'}], test=test_connection)
                    deadline.start(10000)
                    loop.exec()
                    self.assertTrue(deadline.isActive(), 'worker did not return to the chat window')
                    deadline.stop()
                self.assertEqual(errors, [])
                self.assertEqual(received, [False, True])
                self.assertEqual(replies, [reply, reply])
            finally:
                client.shutdown()
                server.shutdown()


if __name__ == '__main__':
    unittest.main()
