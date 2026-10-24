"""Cold chat startup and slow HTTP must not stop native pet frames or dragging.

Uses a loopback mock and disposable settings; never uses saved provider credentials.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import Pet
from pet_chat.config import ProviderConfig
from pet_chat.remote import ChatClient
from visual_style import APPEARANCE_REVISION
from worker_command import worker_command


class Server(BaseHTTPRequestHandler):
    received = []
    def log_message(self, *_): pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.received.append(request['messages'][-1]['content'])
        if request['model'] == 'slow':
            time.sleep(.6)
        body = json.dumps({'choices': [{'message': {'content': '[开心]在呢！'}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class NoStartup:
    supported = False
    def enabled(self): return False


def wait_for(predicate, timeout=10):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        QTest.qWait(10)
    assert predicate(), 'Timed out'


app = QApplication([])
output = ROOT / 'preview/chat-parallel-check'
output.mkdir(parents=True, exist_ok=True)
server = ThreadingHTTPServer(('127.0.0.1', 0), Server)
threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory(dir=output) as scratch:
    os.environ['LOCALAPPDATA'] = scratch
    settings = QSettings(str(Path(scratch)/'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'live2d')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=Path(scratch)/'data', startup=NoStartup(), settings=settings,
              characters_dir=Path(scratch)/'characters')
    client = None
    pulse = QTimer()
    try:
        assert pet.live2d_renderer is not None
        pet.panel.progress_timer.stop()
        pet.dock_edge = ''
        pet.move(500, 250)
        pet.open_chat()
        chat = pet.chat_window
        chat.config = ProviderConfig(f'http://127.0.0.1:{server.server_port}/v1',
                                     'slow', 'fake-test-key', False, False)
        pet.behavior.react('happy', 5)
        samples = []
        pulse.timeout.connect(lambda: samples.append((time.monotonic(), pet.phase)))
        pulse.start(20)
        program, args = worker_command('chat')
        delayed = [ '-c', 'import time,runpy;time.sleep(1.2);runpy.run_path(' +
                   repr(args[0]) + ',run_name="__main__")']
        with patch('pet_chat.remote.worker_command', return_value=(program, delayed)):
            chat.input.setPlainText('今天陪我聊聊吧')
            started = time.monotonic()
            chat.send_message()
            send_seconds = time.monotonic() - started
            client = chat.client
            assert chat.pending and client.active is not None
            assert not client.ready, 'This must exercise the first startup'
            QTest.qWait(350)
            assert len(samples) >= 5, 'Animation event loop stopped during cold startup'
            assert len({phase for _, phase in samples}) >= 4
            assert pet.behavior.activity == 'happy' and pet.behavior.elapsed > .15
            # Actual widget handlers, with synthetic Qt input, while still loading.
            pet.grab()
            hit = pet.head_region.boundingRect().center()
            QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=hit)
            pet.begin_drag()
            assert pet.dragging and client.active is not None
            pet.drag_to(pet.press_point + QPoint(60, 25))
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=hit)
            assert not pet.dragging
            wait_for(lambda: chat.pending is None)
        assert len(chat.store.history(chat.character)) == 2, chat.status.text()
        warm_pid = client.process.processId()
        chat.input.setPlainText('再聊一下')
        chat.send_message()
        chat.stop()
        chat.input.setPlainText('这条才是新的')
        chat.send_message()
        wait_for(lambda: chat.pending is None)
        assert client.process.processId() == warm_pid, 'Reuse warmed network runtime'
        history = chat.store.history(chat.character)
        assert len(history) == 4 and history[-2]['content'] == '这条才是新的'
        # Crash recovery uses a new helper and never waits in the UI path.
        client.process.kill()
        wait_for(lambda: client.process.state() == QProcess.ProcessState.NotRunning)
        chat.input.setPlainText('后台恢复后继续聊')
        chat.send_message()
        wait_for(lambda: chat.pending is None)
        assert len(chat.store.history(chat.character)) == 6, chat.status.text()
        # A cancellation during cold startup must not reach the HTTP server later.
        cold = ChatClient()
        try:
            completed, failed = [], []
            cold.completed.connect(completed.append)
            cold.failed.connect(failed.append)
            with patch('pet_chat.remote.worker_command', return_value=(program, delayed)):
                cold.start(chat.config, [dict(role='user', content='cancel me')])
            cold.cancel()
            wait_for(lambda: cold.ready)
            QTest.qWait(100)
            assert not completed and not failed and cold.pending is None
            assert 'cancel me' not in Server.received
        finally:
            cold.shutdown()
        gaps = [b[0]-a[0] for a,b in zip(samples,samples[1:])]
        report = dict(send_return_seconds=round(send_seconds, 4),
                      animation_samples=len(samples), max_event_gap_seconds=round(max(gaps), 4),
                      delayed_start_seconds=1.2, synthetic_drag_during_loading=True,
                      warm_reuse=True, stale_reply_ignored=True, crash_retry=True,
                      cold_cancel=True, uses_paid_api=False)
        (output/'parallel-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('PASS:', json.dumps(report))
    finally:
        pulse.stop()
        if getattr(pet, 'chat_window', None):
            pet.chat_window.shutdown()
            pet.chat_window.hide()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.tray.hide()
        pet.hide()
        pet.panel.store.close()
        pet.close_live2d()
server.shutdown()
server.server_close()
