"""Offline UI boundaries: provider isolation, QR stages and metadata-only actions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QWidget

from deskpet.music.tools.platform_widget import MusicPlatformWidget
from deskpet.music.kugou.widget import KugouWidget


class Page(QWidget):
    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.cancel = Mock()
        self.shutdown = Mock()
        self.state = {}
        self.setStyleSheet("QWidget { background: white; }")


class FakeClient(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancel = Mock()
        self.run = Mock()


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lazy_switch_preserves_provider_state_and_separate_paths(self):
        with tempfile.TemporaryDirectory() as root:
            panel = MusicPlatformWidget(Path(root)/'netease', factories=dict(netease=Page, kugou=Page))
            self.addCleanup(panel.deleteLater)
            self.assertEqual(list(panel.widgets), ['netease'])
            first = panel.current_widget
            self.assertEqual(first.styleSheet(), 'QWidget { background: white; }')
            first.state['query'] = '原来的搜索'
            created, changed = [], []
            panel.widgetCreated.connect(lambda key, value: created.append((key, value)))
            panel.providerChanged.connect(changed.append)
            panel.set_provider('kugou')
            second = panel.current_widget
            self.assertEqual(second.directory, Path(root)/'kugou')
            first.cancel.assert_called_once()
            panel.provider_choice.setCurrentIndex(0)
            self.assertIs(panel.current_widget, first)
            self.assertEqual(first.state['query'], '原来的搜索')
            self.assertEqual(len(created), 1)
            self.assertEqual(changed, ['kugou', 'netease'])
            second.cancel.assert_called_once()
            panel.shutdown()
            panel.shutdown()
            first.shutdown.assert_called_once()
            second.shutdown.assert_called_once()

    def test_ensure_does_not_switch_and_unknown_provider_rejected(self):
        panel = MusicPlatformWidget('cache/netease', factories=dict(netease=Page, kugou=Page))
        self.addCleanup(panel.deleteLater)
        panel.ensure_provider('kugou')
        self.assertEqual(panel.current_provider, 'netease')
        with self.assertRaises(ValueError):
            panel.set_provider('other')


class KugouTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch('deskpet.music.kugou.widget.Client', FakeClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.widget = KugouWidget(self.temp.name)
        self.addCleanup(self.widget.deleteLater)
        self.addCleanup(self.widget.shutdown)

    def tracks(self):
        return [dict(id='A'*32, title='<b>一</b>', artists='歌手', album_audio_id=123, pay_type=0, url='https://invalid.test', token='secret'),
                dict(id='B'*32, title='二', artists='歌手')]

    def test_multiselect_play_and_download_emit_metadata_without_credentials(self):
        widget = self.widget
        widget._fill_songs(self.tracks())
        for i in range(2):
            widget.songs.topLevelItem(i).setSelected(True)
        played, downloaded = [], []
        widget.playRequested.connect(lambda tracks, start: played.append((tracks, start)))
        widget.downloadRequested.connect(lambda tracks, lrc: downloaded.append((tracks, lrc)))
        widget.play_song()
        widget.download_songs(True)
        self.assertEqual(len(played[0][0]), 2)
        self.assertEqual(played[0][1], 0)
        self.assertNotIn('token', played[0][0][0])
        self.assertNotIn('url', played[0][0][0])
        self.assertEqual(downloaded[0][0][0]['pay_type'], 0)
        self.assertEqual(played[0][0][0]['album_audio_id'], '123')
        self.assertEqual(downloaded[0][1], True)
        self.assertEqual(widget.songs.topLevelItem(0).text(0), '<b>一</b>')

    def test_qr_scanned_is_not_logged_in_and_cancel_does_not_change_session(self):
        widget = self.widget
        changes = []
        widget.sessionChanged.connect(lambda: changes.append(True))
        widget._completed('qr', dict(key='test', url='https://h5.kugou.com/test'))
        self.assertTrue(widget.qr_timer.isActive())
        widget._completed('qr_check', dict(status='scanned'))
        self.assertIn('已扫码', widget.status.text())
        self.assertIsNone(widget.session)
        widget.cancel()
        self.assertFalse(widget.qr_timer.isActive())
        self.assertEqual(widget._qr_key, '')
        self.assertEqual(changes, [])
        widget._completed('qr_check', dict(status='expired'))
        self.assertIn('过期', widget.status.text())

    def test_confirmed_session_is_only_persisted_when_confirmed(self):
        widget = self.widget
        widget.fetch_collections = Mock()
        widget.cache.save_session = Mock()
        widget._completed('qr_check', dict(status='waiting'))
        widget.cache.save_session.assert_not_called()
        session = dict(userid='12', nickname='<script>test</script>', token='not-real')
        widget._completed('qr_check', dict(status='confirmed', session=session))
        self.assertEqual(widget.session, session)
        widget.cache.save_session.assert_called_once_with(session)
        self.assertEqual(widget.account_status.textFormat(), Qt.TextFormat.PlainText)
        widget.fetch_collections.assert_called_once()

    def test_lyrics_result_for_old_selection_cannot_bind_new_selection(self):
        widget = self.widget
        widget._fill_songs(self.tracks())
        widget.songs.setCurrentItem(widget.songs.topLevelItem(1))
        widget._completed('song_selected', dict(self.tracks()[0], lrc='[00:01]test'))
        emitted = []
        widget.lyricsReady.connect(lambda *args: emitted.append(args))
        widget.bind_selected()
        self.assertEqual(emitted, [])
        self.assertEqual(widget.lyric_view.toPlainText(), '')

    def test_failure_retains_displayed_playlist_and_session(self):
        widget = self.widget
        widget.session = dict(userid='12', token='not-real')
        data = dict(id='42', title='test', tracks=self.tracks(), total=2, complete=True)
        widget._show_playlist(data)
        widget._failed('playlist', '<b>网络中断</b>', False)
        self.assertEqual(widget.songs.topLevelItemCount(), 2)
        self.assertIs(widget._current_playlist, data)
        self.assertIsNotNone(widget.session)
        self.assertEqual(widget.status.textFormat(), Qt.TextFormat.PlainText)

    def test_search_and_link_dispatch(self):
        widget = self.widget
        service = Mock()
        widget._service = Mock(return_value=service)
        widget._run = Mock()
        widget.link.setText('测试歌手')
        widget.fetch_link()
        service.search.assert_called_once_with('测试歌手')
        shared = '分享酷狗歌单 https://t.kugou.com/example 点击收听'
        widget.link.setText(shared)
        widget.fetch_link()
        service.resolve_playlist.assert_called_once_with(shared)
        service.playlist.assert_not_called()
        self.assertEqual(widget._run.call_args.args[0], 'playlist')
        widget.link.setText('user_42_1')
        widget.fetch_link()
        service.playlist.assert_called_once_with('user_42_1')

    def test_inherited_snapshot_enumeration_keeps_kugou_opaque_ids(self):
        widget = self.widget
        for key, private in [('collection_test42', False), ('user_42_1', True)]:
            data = dict(id=key, title='测试快照', tracks=self.tracks(), total=2, complete=True)
            widget.cache.save_snapshot('playlist', key, data, private)
            snapshots = widget.cache.snapshots(private)
            self.assertEqual([raw['id'] for raw in snapshots], [key])
            self.assertEqual(snapshots[0]['data']['tracks'], self.tracks())
            self.assertIn('fetched_at', snapshots[0])

    def test_queued_completion_cancel_and_same_kind_replacement_are_ignored(self):
        widget = self.widget
        widget._run('search', iter(()))
        old = widget.client.run.call_args.args[0]
        QTimer.singleShot(0, lambda: widget.client.completed.emit(old, dict(tracks=self.tracks())))
        widget.cancel()
        self.app.processEvents()
        self.assertEqual(widget.songs.topLevelItemCount(), 0)
        widget._run('search', iter(()))
        old = widget.client.run.call_args.args[0]
        widget._run('search', iter(()))
        current = widget.client.run.call_args.args[0]
        self.assertNotEqual(old, current)
        widget.client.completed.emit(old, dict(tracks=self.tracks()))
        self.assertEqual(widget.songs.topLevelItemCount(), 0)
        widget.client.failed.emit(old, 'old session expired', True)
        self.assertTrue(widget._busy)
        widget.client.completed.emit(current, dict(tracks=self.tracks(), total=2))
        self.assertEqual(widget.songs.topLevelItemCount(), 2)

    def test_cancelled_qr_confirmation_cannot_restore_old_session(self):
        widget = self.widget
        widget._run('qr_check', iter(()))
        token = widget.client.run.call_args.args[0]
        result = dict(status='confirmed', session=dict(userid='12', token='old'))
        QTimer.singleShot(0, lambda: widget.client.completed.emit(token, result))
        widget.cancel()
        widget._run('qr_check', iter(()))
        self.app.processEvents()
        self.assertIsNone(widget.session)
        self.assertTrue(widget._busy)

    def test_shutdown_ignores_late_completion(self):
        widget = self.widget
        widget.shutdown()
        widget._completed('search', dict(tracks=self.tracks(), total=2))
        self.assertEqual(widget.songs.topLevelItemCount(), 0)


if __name__ == '__main__':
    unittest.main()
