"""Offline snapshot loading, privacy generations and small JSON fixtures."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from deskpet.music.tools.snapshot_loader import SnapshotLoader
from deskpet.music.netease.storage import Cache
from deskpet.music.netease.widget import NeteaseWidget
from deskpet.music.kugou.widget import KugouWidget


class SnapshotLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        for _ in range(200):
            if predicate():
                return
            QTest.qWait(5)
        self.assertTrue(predicate(), 'background snapshot read did not finish')

    def test_cancelled_storage_scan_stops_between_small_files(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Cache(Path(folder))
            for key in ('1', '2', '3'):
                cache.save_snapshot('playlist', key, dict(title=key, tracks=[], count=0, total=0))
            count = []
            original = cache.snapshot

            def read(*args, **kwargs):
                count.append(args)
                return original(*args, **kwargs)

            with patch.object(cache, 'snapshot', side_effect=read):
                rows = cache.snapshots(cancel=lambda: len(count) >= 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(count), 1)

    def test_loader_discards_cancelled_and_closed_generations(self):
        loader = SnapshotLoader()
        received = []
        loader.loaded.connect(lambda rows, failed: received.append(rows))
        generation = loader.generation
        loader.cancel()
        loader._finish(generation, ['private data'], False)
        self.assertEqual(received, [])
        generation = loader.generation
        loader.close()
        loader._finish(generation, ['late data'], False)
        self.assertEqual(received, [])

    def test_snapshot_rows_open_original_data_without_qvariant_track_copy(self):
        for widget_class in (NeteaseWidget, KugouWidget):
            with self.subTest(widget=widget_class.__name__), tempfile.TemporaryDirectory() as folder:
                widget = widget_class(Path(folder))
                data = dict(title='fixture', tracks=[dict(id='1')], count=1, total=1)
                try:
                    widget._snapshots_loaded([dict(id='1', fetched_at='date', data=data)], False)
                    self.assertEqual(widget.snapshot_list.count(), 1)
                    self.assertIsInstance(widget.snapshot_list.item(0).data(Qt.UserRole), int)
                    widget.snapshot_list.setCurrentRow(0)
                    with patch.object(widget, '_show_playlist') as show:
                        widget.open_snapshot()
                    show.assert_called_once_with(data, 'date')
                finally:
                    widget.shutdown()
                    widget.close()

    def test_both_widgets_defer_io_and_logout_rejects_private_results(self):
        for widget_class in (NeteaseWidget, KugouWidget):
            with self.subTest(widget=widget_class.__name__), tempfile.TemporaryDirectory() as folder:
                # No real sessions, credentials, HTTP, or user cache are involved.
                gui_thread = threading.get_ident()
                started, release = threading.Event(), threading.Event()
                calls = []

                def snapshots(private=False, *, cancel=None):
                    calls.append((private, threading.get_ident()))
                    if private:
                        started.set()
                        release.wait(2)
                    return [dict(id='1', fetched_at='2026-11-17', data=dict(
                        title='private' if private else 'public', tracks=[], count=0, total=0))]

                with patch.object(Cache, 'snapshots', side_effect=snapshots):
                    widget = widget_class(Path(folder))
                self.assertEqual(calls, [])  # Construction performs no snapshot scan.
                try:
                    with patch.object(widget.cache, 'snapshots', side_effect=snapshots), \
                            patch.object(widget.cache, 'clear_private'), \
                            patch.object(widget, 'fetch_collections'):
                        widget.session = dict(uid='1', userid='1', nickname='fixture')
                        self.assertEqual(calls, [])
                        widget.show()
                        QTest.qWait(10)
                        self.assertEqual(calls, [])
                        widget.tabs.setCurrentIndex(1)
                        self.wait_until(started.is_set)
                        self.assertTrue(all(thread != gui_thread for _, thread in calls))
                        old_generation = widget._snapshot_loader.generation
                        widget._logout(False)
                        self.assertEqual(widget.snapshot_list.count(), 0)
                        release.set()
                        widget._snapshot_loader._finish(old_generation, [dict(
                            id='private', fetched_at='date', data=dict(title='private', tracks=[]))], False)
                        self.wait_until(lambda: not widget._snapshot_loader.jobs)
                        self.assertTrue(all('private' not in widget.snapshot_list.item(i).text()
                                            for i in range(widget.snapshot_list.count())))
                        widget._refresh_snapshots()
                        widget.shutdown()
                        generation = widget._snapshot_loader.generation
                        widget._snapshot_loader._finish(generation, ['late result'], False)
                        self.wait_until(lambda: not widget._snapshot_loader.jobs)
                finally:
                    release.set()
                    widget.shutdown()
                    widget.close()


if __name__ == '__main__':
    unittest.main()
