"""Actual WebView2/video-ended integration using a silent, local in-memory fixture."""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QProcess
from PySide6.QtWidgets import QApplication
from main import MusicPanel


def wait_for(condition, timeout=35):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        app.processEvents()
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError('Web playback timeout: ' + panel.bilibili.note.text() +
                         ' ' + str(panel.bilibili.diagnostic)[:2500])


app = QApplication([])
with tempfile.TemporaryDirectory(prefix='tianyi-web-test-') as scratch:
    os.environ['LOCALAPPDATA'] = scratch
    settings = QSettings(str(Path(scratch) / 'settings.ini'), QSettings.Format.IniFormat)
    panel = MusicPanel(SimpleNamespace(playing=False, set_variant=lambda _: None),
                       data_dir=Path(scratch) / 'data', settings=settings)
    web = panel.bilibili
    web.worker_args = ['--self-test']
    panel.volume.setValue(0)
    try:
        web.input.setText('https://example.com/video/BV1xx411c7mu')
        assert not web.add_link()
        assert web.process.state() == QProcess.ProcessState.NotRunning
        web.input.setText('https://www.bilibili.com/video/BV1xx411c7mu/')
        assert web.add_link()
        web.play_row(0)
        wait_for(lambda: web.playing)
        web.input.setText('https://www.bilibili.com/video/BV1xx411c7mD/')
        assert web.add_link()
        assert len(web.queue.paths) == 2, 'songs added during playback should join the queue'
        pid = web.process.processId()
        web.toggle()
        wait_for(lambda: not web.playing)
        assert web.queue.index == 0 and web.active
        web.toggle()
        wait_for(lambda: web.playing)
        wait_for(lambda: web.queue.index == 1)
        assert web.process.processId() == pid, 'next song should reuse the owned web window'
        wait_for(lambda: not web.active)
        wait_for(lambda: web.process.state() == QProcess.ProcessState.NotRunning)
        assert '播完' in web.note.text()
        assert not panel.pet.playing
        assert panel.store.stats()['total'] > 0
        assert panel._player is None and panel._audio is None, 'Bilibili must not initialize local audio'
        assert len(__import__('bilibili_links').load_web_tracks(settings.value('bilibili_tracks'))) == 2
        web.list.setCurrentRow(1)
        web.remove()
        assert len(web.queue.paths) == 1, 'removed current song must leave the queue'
        print('PASS: actual WebView2 start, pause/resume, ended->next, window reuse, final close and listening record')
    finally:
        web.watchdog.stop()
        web.shutdown()
        panel.progress_timer.stop()
        if panel._audio_router is not None:
            panel._audio_router.poll.stop()
        if panel._player is not None:
            panel._player.stop()
        panel.store.close()
        panel.hide()
