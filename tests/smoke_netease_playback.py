"""Isolated real-Pet cloud queue checks; no network, CDN, or actual audio IO."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from main import Pet
from music_tools.clock import playback_snapshot
from audio.remote import RemotePlayer
from visual_style import APPEARANCE_REVISION


class NoStartup:
    supported = False
    def enabled(self): return False


class AudioStub(QObject):
    def __init__(self):
        super().__init__()
        self.ready, self.generation = True, 0
        self.last_report = time.monotonic()
        self.commands = []
    def send(self, command): self.commands.append(command)
    def shutdown(self): pass


class ControlledClient(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str, bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.requests, self.cancellations = [], 0
        self.kind = ''
    def run(self, kind, operation):
        self.kind = kind
        try:
            self.requests.append((kind, next(operation)))
        finally:
            operation.close()
    def cancel(self): self.cancellations += 1
    def resolve(self, result): self.completed.emit(self.kind, result)


TRACKS = [dict(id=str(index), title=f'合成曲目{index}', artists='合成测试', duration=90000)
          for index in (101, 102, 103)]


def media(item_id, trial=False):
    return dict(id=str(item_id), url=f'https://m1.music.126.net/synthetic-{item_id}.mp3',
                unavailable=False, trial=trial, trial_start_ms=60000 if trial else 0)


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='cloud-playback-') as temporary:
        root = Path(temporary)
        settings = QSettings(str(root / 'test.ini'), QSettings.Format.IniFormat)
        settings.setValue('character_selection', 'refined')
        settings.setValue('appearance_revision', APPEARANCE_REVISION)
        pet = Pet(data_dir=root, settings=settings, startup=NoStartup())
        companion = pet.music_companion
        try:
            assert companion is not None, pet.music_startup_error
            pet.timer.stop()
            pet.panel.progress_timer.stop()
            companion.timer.stop()
            if hasattr(companion.beats, 'set_enabled'):
                companion.beats.set_enabled(False)
            else:
                companion.beats.enabled = False
            panel = pet.panel
            engine = AudioStub()
            panel.engine = engine
            panel._player = player = RemotePlayer(engine)
            with patch('netease_music.playback.Client', ControlledClient):
                companion.open(0)
            playback, cloud = companion.playback, companion.cloud
            assert isinstance(playback.client, ControlledClient)
            before_growth = dict(panel.store.pet())

            def start(mode='order', index=0):
                panel.queue.mode = mode
                playback.play(TRACKS, index)
                assert playback.current['id'] == TRACKS[index]['id'] and playback.loading
                assert playback.client.requests[-1][1].url.endswith('/api/song/enhance/player/url')

            def resolve(trial=False):
                playback.client.resolve(media(playback.current['id'], trial))
                assert playback.media_ready

            start()
            resolve()
            assert engine.commands[-1]['cmd'] == 'play'
            panel.step(1)
            assert playback.current['id'] == '102'
            resolve()
            panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            assert playback.current['id'] == '103'
            resolve()
            before = len(playback.client.requests)
            panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            assert len(playback.client.requests) == before and not playback.want_play
            start('loop', 2);resolve()
            panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            assert playback.current['id'] == '101'
            start('single', 1);resolve()
            panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
            assert playback.current['id'] == '102'
            resolve();panel.step(1)
            assert playback.current['id'] == '103', 'manual next must escape single repeat'
            with patch('music_tools.library.random.shuffle', side_effect=lambda bag: bag.reverse()):
                start('shuffle', 0);resolve()
                first = playback.current['id']
                panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
                second = playback.current['id'];resolve()
                panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)
                third = playback.current['id']
                assert len({first, second, third}) == 3
                panel.step(-1)
                assert playback.current['id'] == second

            # Pausing during resolution is a durable intent, not just a player command.
            start()
            panel.toggle()
            assert playback.want_play is False
            engine.commands.clear()
            resolve()
            assert not any(command['cmd'] == 'play' for command in engine.commands)
            panel.toggle()
            assert engine.commands[-1]['cmd'] == 'play'

            # Direct late callback injection exercises the controller's second guard.
            start()
            panel.activate_local()
            engine.commands.clear()
            playback.client.completed.emit('media', media('101'))
            playback.lyric_client.completed.emit('lyrics', dict(id='101', title='旧曲', lrc='[00:00]旧歌词'))
            assert not any(command['cmd'] == 'play' for command in engine.commands)
            assert companion.lyrics.store.binding('netease:101') is None
            start()
            panel.activate_web()
            engine.commands.clear()
            playback.client.completed.emit('media', media('101'))
            assert not any(command['cmd'] == 'play' for command in engine.commands)
            start()
            cloud.logout()
            engine.commands.clear()
            playback.client.completed.emit('media', media('101'))
            assert not playback.active and not any(command['cmd'] == 'play' for command in engine.commands)
            start()
            panel.step(1)
            engine.commands.clear()
            playback.client.completed.emit('media', media('101'))
            assert playback.current['id'] == '102' and not any(command['cmd'] == 'play' for command in engine.commands)

            # Trial playback reports native clip time, while lyrics use the full-song offset.
            resolve(trial=True)
            engine.last_report = time.monotonic()
            player.values.update(position=1500, duration=30000, state=1, status=5, playback_rate=1.0)
            snapshot = playback_snapshot(panel)
            assert (snapshot.source_key, snapshot.position_ms, snapshot.duration_ms, snapshot.valid) == (
                'netease:102', 61500, 90000, True)
            playback.lyric_client.resolve(dict(id='102', title='同名不同ID合成曲',
                lrc='[01:00.000]试听首句\n[01:01.000]试听当前句\n[01:02.000]下一句'))
            assert companion.lyrics.store.binding('netease:102')['song_id'] == '102'
            assert companion.lyrics.store.binding('netease:101') is None
            companion.tick()
            assert companion.lyrics.overlay.text == '试听当前句'
            player.values.update(state=2, position=500)
            companion.tick()
            assert not companion.snapshot.playing and companion.snapshot.position_ms == 60500
            assert companion.lyrics.overlay.text == '试听首句'
            engine.last_report = time.monotonic() - 4
            companion.tick()
            assert not companion.snapshot.valid and not companion.lyrics.overlay.isVisible()
            assert dict(panel.store.pet()) == before_growth
            # A logout while the folder picker is open cancels that pending intent too.
            def logout_while_choosing(*args, **kwargs):
                cloud.sessionChanged.emit()
                return str(root)
            with patch('netease_music.download_queue.QFileDialog.getExistingDirectory', side_effect=logout_while_choosing), \
                 patch.object(companion.downloads.client, 'run') as prepare_request:
                companion.downloads.start(TRACKS)
                prepare_request.assert_not_called()
                assert not companion.downloads.running
            print('PASS cloud playback: queue next/end/order/loop/single/shuffle; loading-pause; '
                  'late source/account isolation; exact lyric ID; native clock and trial offset; no growth change')
        finally:
            if companion:
                companion.shutdown()
                if companion.window: companion.window.hide()
            if pet.mod_host: pet.mod_host.shutdown()
            pet.timer.stop()
            pet.panel.progress_timer.stop()
            pet.panel.bilibili.shutdown()
            pet.panel.shutdown_audio()
            pet.close_live2d()
            pet.tray.hide()
            pet.panel.store.close()
            pet.panel.hide()
            pet.hide()


if __name__ == '__main__':
    main()
