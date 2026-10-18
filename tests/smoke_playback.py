"""Exercise real MP3 decoding, seek, persistence and looping with silent audio."""
import os
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
if sys.platform == 'win32':
    os.environ.setdefault('QT_MEDIA_BACKEND', 'windows')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import imageio_ffmpeg
from PySide6.QtCore import QSettings, QUrl, QEvent, QCoreApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from main import MusicPanel
from audio_routing import device_id


def wait_for(condition, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for audio state')


def dispose(panel):
    if getattr(panel, '_disposed', False):
        return
    panel._disposed = True
    panel.progress_timer.stop()
    panel.audio_router.poll.stop()
    panel.autoplay_requested = False
    panel.player.stop()
    panel.player.setSource(QUrl())
    panel.shutdown_audio()
    panel.store.close()
    panel.hide()
    panel.player.deleteLater()
    panel.audio.deleteLater()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


with tempfile.TemporaryDirectory(prefix='天依 音乐 ') as scratch, ExitStack() as cleanup:
    app = QApplication([])
    app.setApplicationName('TianyiPlaybackTest')
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, scratch)
    song = Path(scratch) / '静音 测试.mp3'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'anullsrc=r=44100:cl=mono', '-t', '12', '-codec:a', 'libmp3lame', str(song)],
                   check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    pet = SimpleNamespace(playing=False, set_variant=lambda _: None)
    settings_file = str(Path(scratch) / 'settings.ini')
    first = MusicPanel(pet, data_dir=Path(scratch) / 'first',
                       settings=QSettings(settings_file, QSettings.Format.IniFormat))
    cleanup.callback(dispose, first)
    first.volume.setValue(0)
    first.import_paths([str(song)])
    first.play_row(0)
    wait_for(lambda: first.player.duration() > 11000 and first.player.position() > 2200)
    assert first.store.stats()['total'] > 0
    # Route real decoded media between the available outputs without changing Windows defaults.
    outputs = first.audio_router.outputs
    initial = device_id(first.audio.device())
    alternative = next((d for d in outputs if device_id(d) != initial), None)
    if alternative is not None:
        before = first.player.position()
        source = first.current_path()
        first.output_choice.setCurrentIndex(first.output_choice.findData(device_id(alternative)))
        wait_for(lambda: device_id(first.audio.device()) == device_id(alternative)
                 and first.player.position() > before + 350
                 and first.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        assert first.current_path() == source
        first.output_choice.setCurrentIndex(0)
        wait_for(lambda: device_id(first.audio.device()) == device_id(first.audio_router.default)
                 and first.player.position() > before + 600)
        print('PASS: real output switch during playback and return to system default', flush=True)
    first.seek.setValue(5000)
    first.seek_to()
    wait_for(lambda: first.player.position() >= 5000)
    first.toggle()
    if alternative is not None:
        paused_at = first.player.position()
        first.output_choice.setCurrentIndex(first.output_choice.findData(device_id(alternative)))
        wait_for(lambda: device_id(first.audio.device()) == device_id(alternative)
                 and abs(first.player.position() - paused_at) < 300)
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert first.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        assert abs(first.player.position() - paused_at) < 350, (
            paused_at, first.player.position(), first.pending_seek,
            first.player.mediaStatus(), first.player.errorString())
    first.save()
    saved_position = first.player.position()
    dispose(first)
    second = MusicPanel(pet, data_dir=Path(scratch) / 'second',
                        settings=QSettings(settings_file, QSettings.Format.IniFormat))
    cleanup.callback(dispose, second)
    second.volume.setValue(0)
    assert second._player is None, 'restoring metadata must not initialize audio at startup'
    second.sample()
    second.save()
    assert second._player is None, 'idle sampling and saving must keep audio lazy'
    assert int(second.settings.value('current_position')) == saved_position
    second.ensure_audio()
    try:
        wait_for(lambda: second.pending_seek is None and second.player.duration() > 11000
                 and abs(second.player.position() - saved_position) < 250)
    except AssertionError:
        print('Restore diagnostics:', second.player.source().toLocalFile(), second.pending_seek,
              second.player.duration(), second.player.mediaStatus(), second.player.errorString(),
              second.paths, second.settings.value('current_position'), flush=True)
        raise
    assert second.current_path() == str(song.resolve())
    assert second.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    assert abs(second.player.position() - saved_position) < 250
    second.mode_choice.setCurrentIndex(second.mode_choice.findData('single'))
    second.seek.setValue(second.player.duration() - 800)
    second.seek_to()
    second.toggle()
    wait_for(lambda: second.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
             and 50 < second.player.position() < 1500)
    assert second.pending_seek is None
    dispose(second)
print('PASS: real MP3 decode, listening sample, seeking, paused restoration and single-track repeat')
