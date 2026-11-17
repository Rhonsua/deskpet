"""Downloads use disposable files and synthetic accounts; no network or playback."""
import hashlib
import io
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request
import wave
import zipfile

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from deskpet.music.players import bilibili_download as download, audio_converter as converter
from deskpet.music.players.bilibili_download_ui import BilibiliDownloads
from deskpet.music.players.bilibili_import import BilibiliImport, Source
from deskpet.music.players.bilibili_player import BilibiliPlayer
from deskpet.music.tools.library import MusicLibrary

URL = 'https://www.bilibili.com/video/BV0000000001/'


def staged(directory, part=1):
    folder = Path(tempfile.mkdtemp(prefix='.tianyi-bilibili-', dir=directory))
    source = folder / 'converted.mp3'
    source.write_bytes(b'completed audio')
    return dict(path=str(source), folder=str(folder), title='同名歌曲', id='BV0000000001', part=part)


class DownloadTests(unittest.TestCase):
    def test_all_parts_does_not_expand_unrelated_season(self):
        client = BilibiliImport()
        client.api = Mock(return_value=dict(bvid='BV0000000001', title='演唱会',
            ugc_season=dict(id=123), pages=[dict(page=1, part='第一首'), dict(page=6, part='第六首')]))
        result = client.read(Source('parts', url=URL + '?p=6'))
        self.assertEqual([t['url'] for t in result['tracks']], [URL, URL + '?p=6'])
        self.assertIn('第六首', result['tracks'][1]['title'])
        client.api.assert_called_once()

    def test_cookie_scoped_to_bilibili_and_cancellation_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            stop = threading.Event()
            with download.make_downloader(Path(root), 'SESSDATA=synthetic; other=private', stop, lambda _: None) as ydl:
                self.assertEqual(list(ydl._ies), ['BiliBili'])
                request = Request('https://api.bilibili.com/x/web-interface/view')
                ydl.cookiejar.add_cookie_header(request)
                self.assertEqual(request.get_header('Cookie'), 'SESSDATA=synthetic')
                for url in ('https://example.test/audio', 'http://api.bilibili.com/test'):
                    request = Request(url)
                    ydl.cookiejar.add_cookie_header(request)
                    self.assertIsNone(request.get_header('Cookie'))
                stop.set()
                with self.assertRaises(download.Cancelled):
                    ydl.urlopen('https://api.bilibili.com/test')

    def test_each_part_unique_atomic_conflict_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = staged(root), staged(root, 2)
            one = download.commit_result(first, root)
            two = download.commit_result(second, root)
            self.assertNotEqual(one, two)
            download.dispose_result(first, root)
            download.dispose_result(second, root)
            replacement = staged(root)
            one.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                download.commit_result(replacement, root)
            self.assertEqual(one.read_bytes(), b'original')
            download.commit_result(replacement, root, overwrite=True)
            self.assertEqual(one.read_bytes(), b'completed audio')
            download.dispose_result(replacement, root)
            self.assertEqual(len(list(Path(root).iterdir())), 2)

    def test_partial_download_is_not_saved_and_stage_is_removed(self):
        with tempfile.TemporaryDirectory() as root:
            ydl = Mock()
            ydl.__enter__ = Mock(return_value=ydl)
            ydl.__exit__ = Mock(return_value=False)
            ydl.extract_info.return_value = dict(title='歌曲', duration=30)
            ydl.process_ie_result.side_effect = OSError('incomplete fragment')
            with patch.object(converter, 'ensure_converter', return_value='unused'), \
                    patch.object(download, 'make_downloader', return_value=ydl), self.assertRaises(OSError):
                download.download_mp3(URL, root, tools_directory=root)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_real_local_conversion_and_short_audio_rejected(self):
        try:
            import imageio_ffmpeg
        except ImportError:
            self.skipTest('Optional development converter not installed')
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / 'test.wav', Path(root) / 'test.mp3'
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
                audio.writeframes(bytes(22050 * 2))
            download.transcode(source, output, threading.Event(), ffmpeg=imageio_ffmpeg.get_ffmpeg_exe())
            download.validate_mp3(output, 1)
            with self.assertRaisesRegex(ValueError, '不完整'):
                download.validate_mp3(output, 10)


class ConverterTests(unittest.TestCase):
    def wheel(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('imageio_ffmpeg/binaries/' + converter.BINARY_NAME, b'test binary')
            archive.writestr('imageio_ffmpeg-0.6.0.dist-info/licenses/LICENSE', b'test license')
            archive.writestr('unused-file', b'do not extract')
        return buffer.getvalue()

    @unittest.skipUnless(os.name == 'nt', 'Windows converter bootstrap')
    def test_first_use_verified_cached_and_archives_removed(self):
        payload = self.wheel()
        with tempfile.TemporaryDirectory() as root, patch.object(converter.sys, 'frozen', True, create=True), \
                patch.object(converter.shutil, 'which', return_value=None), \
                patch.object(converter, 'WHEEL_HASH', hashlib.sha256(payload).hexdigest()), \
                patch.object(converter, 'BINARY_HASH', hashlib.sha256(b'test binary').hexdigest()), \
                patch.object(converter, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(payload)) as network:
            executable = converter.ensure_converter(root, threading.Event(), lambda _: None)
            self.assertEqual(executable.read_bytes(), b'test binary')
            self.assertEqual(converter.ensure_converter(root, threading.Event(), lambda _: None), executable)
            network.assert_called_once()
            self.assertEqual(sorted(p.name for p in executable.parent.iterdir()), ['LICENSE', converter.BINARY_NAME])
            executable.write_bytes(b'corrupted')
            converter.ensure_converter(root, threading.Event(), lambda _: None)
            self.assertEqual(network.call_count, 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows converter bootstrap')
    def test_corrupt_wheel_never_installed_and_cancel_cleans_temporary(self):
        payload = self.wheel()
        with tempfile.TemporaryDirectory() as root, patch.object(converter.sys, 'frozen', True, create=True), \
                patch.object(converter.shutil, 'which', return_value=None), \
                patch.object(converter, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(payload)):
            with self.assertRaisesRegex(ValueError, '校验失败'):
                converter.ensure_converter(root, threading.Event(), lambda _: None)
            self.assertEqual(list(Path(root).rglob('prepare-*')), [])
            self.assertEqual(list(Path(root).rglob('*.exe')), [])
            stop = threading.Event()
            def progress(text):
                if ' / 29.8' in text:
                    stop.set()
            with self.assertRaises(download.Cancelled):
                converter.ensure_converter(root, stop, progress)
            self.assertEqual(list(Path(root).rglob('prepare-*')), [])


class DownloadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.owner = QWidget()
        self.owner.settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        self.owner.data_dir = self.root
        self.owner.library = MusicLibrary()
        self.owner.persist_library = Mock(return_value=True)
        self.owner.render_library = Mock()
        self.owner.set_alternating = Mock()
        self.player = BilibiliPlayer(self.owner)
        self.player.watchdog.stop()
        self.player.request_import_account = Mock()
        self.player.cancel_import_account = Mock()
        self.queue = BilibiliDownloads(self.player)
        self.player.downloads = self.queue
        self.queue.parts.start = Mock()
        self.pool = patch('deskpet.music.players.bilibili_download_ui.QThreadPool.globalInstance').start().return_value
        self.tracks = [dict(url=URL, title='P1'), dict(url=URL + '?p=2', title='P2')]

    def tearDown(self):
        self.queue.cancel()
        self.owner.settings.sync()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()
        patch.stopall()
        self.temp.cleanup()

    def start(self, *, all_parts=False):
        self.queue.start(self.tracks, self.root, all_parts=all_parts)
        self.player.accountReady.emit(dict(request=self.queue.account_request))

    def test_all_parts_reads_video_then_downloads_and_preserves_local_selection(self):
        active = self.owner.library.active_id
        self.start(all_parts=True)
        self.queue.parts.start.assert_called_once_with(Source('parts', url=URL), '')
        self.pool.start.assert_not_called()
        self.queue.parts_ready(dict(tracks=self.tracks), '')
        self.assertEqual(self.queue.job.track, self.tracks[0])
        self.queue.completed(staged(self.root), '')
        self.app.processEvents()
        self.assertEqual(self.queue.job.track, self.tracks[1])
        self.assertEqual(self.owner.library.active_id, active)
        self.assertEqual(len(self.owner.library.playlists[-1]['paths']), 1)
        self.assertEqual(self.owner.library.paths, [])

    def test_cancelled_result_does_not_save_or_modify_playlist(self):
        self.start()
        result = staged(self.root)
        self.queue.cancel()
        self.queue.completed(result, '')
        self.assertFalse(Path(result['folder']).exists())
        self.owner.persist_library.assert_not_called()
        self.assertFalse(list(self.root.glob('*.mp3')))

    def test_later_batch_reuses_download_playlist_without_changing_active(self):
        active = self.owner.library.active_id
        self.start()
        self.queue.completed(staged(self.root), '')
        self.queue.cancel()
        self.app.processEvents()
        self.queue.start(self.tracks, self.root)
        self.queue.add_to_local(self.root / 'other.mp3')
        self.assertEqual(len(self.owner.library.playlists), 2)
        self.assertEqual(len(self.owner.library.playlists[-1]['paths']), 2)
        self.assertEqual(self.owner.library.active_id, active)

    def test_overwrite_no_advances_and_yes_replaces(self):
        self.start()
        for part, answer in [(1, QMessageBox.StandardButton.No), (2, QMessageBox.StandardButton.Yes)]:
            result = staged(self.root, part)
            target = download.target_path(result, self.root)
            target.write_bytes(b'old')
            with patch.object(QMessageBox, 'exec', return_value=answer):
                self.queue.completed(result, '')
            self.app.processEvents()
            self.assertEqual(target.read_bytes(), b'old' if part == 1 else b'completed audio')
        self.assertFalse(self.queue.running)
        self.assertEqual((self.queue.saved, self.queue.skipped), (1, 1))

    def test_cancel_during_overwrite_cannot_start_new_batch_or_commit_old_file(self):
        self.start()
        result = staged(self.root)
        target = download.target_path(result, self.root)
        target.write_bytes(b'keep original')
        def question():
            self.queue.cancel()
            self.queue.start(self.tracks, self.root / 'nonexistent')
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, 'exec', side_effect=question):
            self.queue.completed(result, '')
        self.assertEqual(target.read_bytes(), b'keep original')
        self.assertFalse(self.queue.running)
        self.assertFalse(Path(result['folder']).exists())


if __name__ == '__main__':
    unittest.main()
