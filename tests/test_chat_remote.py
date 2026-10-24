"""IPC framing, cancellation and error cleanup without accessing any API."""
import json
import unittest
from unittest.mock import Mock
from PySide6.QtCore import QCoreApplication, QProcess
from pet_chat.remote import ChatClient


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.client = ChatClient()
        self.client.process = Mock()
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


if __name__ == '__main__':
    unittest.main()
