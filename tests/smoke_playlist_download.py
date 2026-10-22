"""Synthetic whole-playlist queue and durable exact local lyric binding."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QWidget
from music_tools.library import MusicLibrary
from music_lyrics import LyricsController
from netease_music.download_queue import NeteaseDownloads
from netease_music.service import Service


class Cloud(QWidget):
    sessionChanged = Signal()
    def _service(self): return Service()
    def set_playback_status(self, message): self.message = message
    def _failed(self, *args): self.error = args


class Client(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str, bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls = []
    def run(self, kind, operation):
        try: self.calls.append((kind, next(operation)))
        finally: operation.close()
    def cancel(self): pass


class Transfer(QObject):
    completed = Signal(str, str)
    failed = Signal(str)
    warning = Signal(str)
    progress = Signal(int, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls = []
    def start(self, *args, **kwargs): self.calls.append((args, kwargs))
    def cancel(self): pass


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='playlist-download-') as temporary:
        root = Path(temporary)
        pet, cloud = QWidget(), Cloud()
        library = MusicLibrary()
        original_id = library.active_id
        library.add([str(root / 'already-playing.mp3')])
        original_paths = list(library.paths)
        settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
        pet.panel = SimpleNamespace(settings=settings, library=library, render_library=lambda: None)
        companion = QObject()
        companion.pet = pet
        companion.lyrics = LyricsController(pet, root)
        with patch('netease_music.download_queue.Client', Client), patch('netease_music.download_queue.Downloader', Transfer):
            queue = NeteaseDownloads(companion, cloud)
        try:
            tracks = [dict(id=str(i+1), title=f'合成曲目{i}', artists='测试') for i in range(101)]
            queue.start_playlist('987', root)
            assert queue.fetching_playlist and queue.client.calls[-1][0] == 'playlist_download'
            assert queue.client.calls[-1][1].params['id'] == '987'
            queue.client.completed.emit('playlist_download', dict(title='合成歌单', tracks=tracks, total=101, complete=True))
            assert len(queue.items) == 101 and queue.index == 0, 'whole playlist was truncated at selection limit'
            audio = root / 'duplicate (1).mp3'
            lrc = audio.with_suffix('.lrc')
            audio.write_bytes(b'ID3 synthetic fixture, never played')
            lrc.write_text('[00:01]自动绑定测试', encoding='utf-8')
            queue.transfer.completed.emit(str(audio), str(lrc))
            queue.timer.stop()
            source = 'local:' + str(audio.resolve())
            binding = companion.lyrics.store.binding(source)
            assert binding and binding['body'] == '[00:01]自动绑定测试'
            assert Path(binding['song_id']) == lrc
            assert library.active_id == original_id and library.paths == original_paths
            downloaded = next(item for item in library.playlists if item['id'] == queue.local_playlist_id)
            assert downloaded['paths'] == [str(audio.resolve())]
            restored_library = MusicLibrary(settings.value('library_v1'))
            assert restored_library.active_id == original_id and len(restored_library.playlists) == 2
            assert queue.saved_count == queue.bound_count == 1
            queue._next()
            queue.client.failed.emit('prepare', '没有下载权限', False)
            queue.timer.stop()
            assert queue.failed_count == 1 and queue.running
            queue._next()
            assert queue.index == 2, 'one unavailable song blocked remaining tracks'
            queue.cancel()
            queue.transfer.completed.emit(str(root/'late.mp3'), '')
            assert queue.saved_count == 1 and audio.exists() and lrc.exists()
            assert library.active_id == original_id

            queue.start_playlist('987', root)
            queue.client.completed.emit('playlist_download', dict(title='部分歌单', tracks=tracks[:1], total=101, complete=False))
            assert '不完整' in queue.playlist_note
            with patch.object(companion.lyrics, 'import_file', side_effect=sqlite3.OperationalError('disk full')):
                queue.transfer.completed.emit(str(audio), str(lrc))
            queue.timer.stop()
            assert queue.saved_count == 1 and queue.bound_count == 0 and '绑定失败' in queue.results[-1]
            queue._next()
            assert not queue.running and '不完整' in cloud.message
            queue.result_box.close()

            queue.start_playlist('987', root)
            cloud.sessionChanged.emit()
            queue.client.completed.emit('playlist_download', dict(title='迟到', tracks=tracks, total=101, complete=True))
            assert not queue.running and not queue.items
            queue.start_playlist('987', root)
            queue.client.failed.emit('playlist_download', '网络失败', False)
            assert not queue.running and '未开始下载' in cloud.message
            epoch = queue.epoch
            def choose_directory(*args):
                cloud.sessionChanged.emit()
                return str(root)
            with patch('netease_music.download_queue.QFileDialog.getExistingDirectory', side_effect=choose_directory):
                queue.start_playlist('987')
            assert not queue.running and queue.epoch != epoch
            companion.lyrics.shutdown()
            restored = LyricsController(pet, root)
            try:
                assert restored.store.binding(source)['body'] == '[00:01]自动绑定测试'
            finally:
                restored.shutdown()
            print('PASS: full 101-track request, exact persisted LRC binding, local playlist without playback changes, partial results, failures and cancellation')
        finally:
            queue.cancel()
            companion.lyrics.shutdown()
            cloud.close()
            pet.close()


if __name__ == '__main__':
    main()
