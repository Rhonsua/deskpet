"""Actual WebView2 single/list loops and minimizing to the desktop pet tray."""
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


app = QApplication([])
with tempfile.TemporaryDirectory(prefix='tianyi-web-loops-', ignore_cleanup_errors=True) as scratch:
    os.environ['LOCALAPPDATA'] = scratch
    panel = MusicPanel(SimpleNamespace(playing=False, set_variant=lambda _: None),
                       data_dir=Path(scratch)/'data',
                       settings=QSettings(str(Path(scratch)/'test.ini'), QSettings.Format.IniFormat))
    web = panel.bilibili
    if '--packaged' in sys.argv:
        import bilibili_player
        worker = Path(__file__).resolve().parents[1] / 'dist' / 'TianyiPet' / 'TianyiWorker.exe'
        assert worker.is_file()
        bilibili_player.worker_command = lambda _: (str(worker), ['--web-worker'])
    web.worker_args = [] if '--live' in sys.argv else ['--self-test']
    if '--faults' in sys.argv:
        web.worker_args.append('--self-test-faults')
    if '--reload' in sys.argv:
        web.worker_args.append('--self-test-reload')
    panel.volume.setValue(0)
    def wait(condition, timeout=25):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents()
            if condition(): return
            time.sleep(.01)
        raise AssertionError(web.note.text() + ' ' + str(web.metrics) + ' hidden=' + str(web.hidden))
    def finish():
        # Real adaptive streams may revise duration after initial metadata.
        web.send({'cmd': 'seek', 'position': web.metrics['duration']-(3 if '--live' in sys.argv else .3)})
    try:
        urls = (('https://www.bilibili.com/video/BV1GJ411x7h7/',
                 'https://www.bilibili.com/video/av170001/') if '--live' in sys.argv else
                ('https://www.bilibili.com/video/BV1xx411c7mu/',
                 'https://www.bilibili.com/video/BV1xx411c7mD/'))
        for url in urls:
            web.input.setText(url)
            assert web.add_link()
        web.mode.setCurrentIndex(web.mode.findData('single'))
        web.play_row(0)
        wait(lambda: web.playing)
        pid = web.process.processId()
        web.send({'cmd': 'minimize'})
        wait(lambda: web.hidden)
        web.toggle()
        wait(lambda: not web.playing)
        paused_token = web.latch.token
        pause_deadline = time.monotonic() + 1
        while time.monotonic() < pause_deadline:
            app.processEvents()
            time.sleep(.01)
        assert not web.playing and web.latch.token == paused_token, 'background resume must respect explicit pause'
        web.toggle()
        wait(lambda: web.playing)
        fallback_seen = reload_seen = False
        def record_completion(value):
            global fallback_seen, reload_seen
            if value.get('completion_reason') == 'tail_stalled':
                fallback_seen = True
            if value.get('type') == 'waiting' and '重新载入' in value.get('message', ''):
                reload_seen = True
        original_handle = web.handle_event
        def handle_with_record(value):
            record_completion(value)
            original_handle(value)
        web.handle_event = handle_with_record
        for _ in range(2):
            token = web.latch.token
            finish()
            wait(lambda: web.latch.token != token and web.playing)
            assert web.queue.index == 0 and web.hidden and web.process.processId() == pid
            assert web.metrics['position'] < 2, 'single loop must restart from zero'
        web.send({'cmd': 'show'})
        wait(lambda: not web.hidden)
        web.send({'cmd': 'hide'})
        wait(lambda: web.hidden)
        web.mode.setCurrentIndex(web.mode.findData('loop'))
        web.step(1)
        wait(lambda: web.queue.index == 1 and web.playing)
        finish()
        wait(lambda: web.queue.index == 0 and web.playing)
        assert web.hidden and web.process.processId() == pid, 'auto next must not reopen the hidden window'
        finish()
        wait(lambda: web.queue.index == 1 and web.playing)
        web.mode.setCurrentIndex(web.mode.findData('order'))
        finish()
        wait(lambda: not web.active)
        wait(lambda: web.process.state() == QProcess.ProcessState.NotRunning)
        assert panel._player is None
        if '--faults' in sys.argv:
            assert fallback_seen, 'missing-ended fixture must exercise the host completion fallback'
        if '--reload' in sys.argv:
            assert reload_seen, 'failed same-page seeks must recover by reloading once'
        print('PASS: single loops twice from zero, native minimize->tray, show/hide, hidden list wrap, order final close')
    finally:
        web.watchdog.stop()
        web.shutdown()
        panel.shutdown_audio()
        panel.progress_timer.stop()
        panel.store.close()
        panel.hide()
