import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
from deskpet.chat.workbench import Workbench

class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_failed_start_resets_and_signals_once(self):
        work = Workbench()
        process = Mock()
        work.process, work.running = process, True
        stopped = Mock()
        work.stopped.connect(stopped)
        work._error(process, QProcess.FailedToStart)
        self.assertFalse(work.running)
        self.assertIsNone(work.process)
        stopped.assert_called_once()
        work._finished(process)
        stopped.assert_called_once()

    def test_old_process_cannot_finish_new_run(self):
        work = Workbench()
        old, current = Mock(), Mock()
        work.process, work.running = current, True
        work._finished(old)
        work._error(old, QProcess.FailedToStart)
        work._read(old)
        self.assertIs(work.process, current)
        self.assertTrue(work.running)
        current.readAllStandardOutput.assert_not_called()

    def test_timeout_stops_startup_but_not_ready_service(self):
        work = Workbench()
        work.running = True
        work.stop = Mock()
        work._startup_timeout()
        work.stop.assert_called_once()
        work.stop.reset_mock()
        work.url = 'http://127.0.0.1:1234/'
        work._startup_timeout()
        work.stop.assert_not_called()

    def test_shutdown_waits_for_tree_without_event_loop(self):
        work = Workbench()
        process = Mock()
        work.process, work.running = process, True
        work._kill_tree = Mock()
        work.shutdown()
        work._kill_tree.assert_called_once_with(process, wait=True)
        self.assertFalse(work.running)
        self.assertIsNone(work.process)

if __name__ == '__main__':
    unittest.main()
