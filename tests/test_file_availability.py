import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QListWidget
from deskpet.app import MusicPanel
from deskpet.music.tools.file_availability import FileAvailability


class FileAvailabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_blocked_old_scan_never_overwrites_new_playlist(self):
        entered, release, newer = threading.Event(), threading.Event(), threading.Event()
        old = [f'old-{i}.mp3' for i in range(30)]
        new = [f'new-{i}.mp3' for i in range(30)]
        def check(path):
            if str(path).startswith('old-'):
                entered.set()
                release.wait(5)
                return False
            return True

        scanner = FileAvailability()
        received = []
        scanner.ready.connect(lambda ticket, result: (received.append((ticket, result)), newer.set()))
        with patch.object(Path, 'is_file', check):
            scanner.start(old)
            self.assertTrue(entered.wait(2))
            ticket = scanner.start(new)
            try:
                deadline = time.monotonic() + 3
                while not newer.is_set() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertTrue(newer.is_set())
                self.assertEqual(received, [(ticket, dict.fromkeys(new, True))])
            finally:
                release.set()
            deadline = time.monotonic() + 3
            while scanner.jobs and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
            self.assertEqual(len(received), 1)
            self.assertFalse(scanner.jobs)

    def test_stale_result_does_not_change_list_or_cache(self):
        widget = QListWidget()
        widget.addItem('new-0')
        widget.item(0).setToolTip('new-0.mp3')
        panel = SimpleNamespace(file_scan_context=(2, 'new', ('new-0.mp3',)),
                                library=SimpleNamespace(active_id='new'), paths=['new-0.mp3'],
                                file_status={}, list=widget)
        MusicPanel._files_checked(panel, 1, {'new-0.mp3': False})
        self.assertEqual(widget.item(0).text(), 'new-0')
        self.assertEqual(panel.file_status, {})
        MusicPanel._files_checked(panel, 2, {'new-0.mp3': False})
        self.assertEqual(widget.item(0).text(), '失效 · new-0')


if __name__ == '__main__':
    unittest.main()
