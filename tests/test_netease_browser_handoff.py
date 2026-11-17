"""No real browser session: helper state and abandoned-process boundaries."""
import json
import gc
import unittest
import weakref
import sys
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QProcess
from PySide6.QtTest import QSignalSpy
from deskpet.music.netease.browser_login import BrowserLogin
from deskpet.music.players.netease_player_worker import page_state


class BrowserHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_state_uses_native_evaluation_without_promise_bridge(self):
        window = Mock()
        window.run_js.return_value = json.dumps(dict(stage='scanned', renderedProfile=dict(userId='77'), profile=None))
        self.assertEqual(page_state(window)['stage'], 'scanned')
        window.evaluate_js.assert_not_called()
        window.run_js.return_value = None
        self.assertEqual(page_state(window), {})
        window.run_js.return_value = 'navigation-in-progress'
        self.assertEqual(page_state(window), {})

    def test_abandoned_process_cannot_finish_or_read_new_attempt(self):
        login = BrowserLogin()
        self.addCleanup(login.cancel)
        old = login.process
        epoch = login._epoch
        login.cancel()
        login.active = True
        login.buffer = b'new-attempt'
        failures = []
        login.failed.connect(failures.append)
        login._read(old, epoch)
        login._finished(old, epoch)
        login._error(QProcess.ProcessError.FailedToStart, old, epoch)
        self.assertTrue(login.active)
        self.assertEqual(login.buffer, b'new-attempt')
        self.assertEqual(failures, [])

    def test_cancelled_owner_has_no_signal_reference_cycle(self):
        for _ in range(12):
            login = BrowserLogin()
            reference = weakref.ref(login)
            login.cancel()
            login.deleteLater()
            del login
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()
            gc.collect()
            self.assertIsNone(reference())

    def test_replaced_process_is_disconnected_before_deferred_delete(self):
        login = BrowserLogin()
        self.addCleanup(login.cancel)
        previous = login.process
        login._dispose_process(previous)
        login.process = login._new_process()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(login.process.state(), QProcess.ProcessState.NotRunning)

    def test_cancel_retires_running_helper_without_waiting_or_killing_new_attempt(self):
        login = BrowserLogin()
        previous = login.process
        previous.start(sys.executable, ['-c', 'import time; time.sleep(5)'])
        self.assertTrue(previous.waitForStarted(2000))
        with patch.object(previous, 'waitForFinished', side_effect=AssertionError('GUI wait')):
            login.cancel()
        current = login.process
        self.assertIsNot(previous, current)
        self.assertIs(previous.parent(), self.app)
        # The old helper is allowed to finish after its page has been destroyed.
        ended = QSignalSpy(previous.finished)
        login.deleteLater()
        self.assertTrue(ended.wait(2500))
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
