"""Opt-in real local speech check; no paid API, user settings or history.

Run with the desktop Python after installing the optional voice environment:
    .venv/Scripts/python.exe tests/smoke_speech_local.py
Temporary chat databases, synthesis files and caches are removed on exit.
Playback uses the real Qt backend at zero volume. No model downloads occur.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import wave
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, QTimer, QProcess
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from deskpet.app import Pet
from deskpet.chat.config import ProviderConfig
from deskpet.chat.companion import CompanionState
from deskpet.ui.appearance import APPEARANCE_REVISION


class Handler(BaseHTTPRequestHandler):
    replies = ('[开心]欢迎回来呀，我会在这里陪着你。',
               '好呀，休息一会儿，我们再一起加油。',
               '窗外好安静呀，一起听听风吧。')
    count = 0

    def log_message(self, *_):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        text = self.replies[type(self).count % len(self.replies)]
        type(self).count += 1
        payload = json.dumps({'choices': [{'message': {'content': text}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class Startup:
    supported = False

    def enabled(self):
        return False


def wait_until(predicate, timeout=20, detail=lambda: ''):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Timed out: ' + detail()


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app = QApplication.instance() or QApplication([])
    result = {'provider': 'local fixture; no paid API', 'replies': []}
    try:
        with tempfile.TemporaryDirectory(prefix='tianyi-speech-') as temp:
            settings = QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('character_selection', 'refined')
            settings.setValue('appearance_revision', APPEARANCE_REVISION)
            settings.setValue('speech/enabled', True)
            settings.setValue('speech/volume', 0)
            started = time.monotonic()
            pet = Pet(data_dir=Path(temp), settings=settings, startup=Startup())
            chat = None
            heartbeat = QTimer()
            ticks = []
            phase = 'startup warmup'
            heartbeat.timeout.connect(lambda: ticks.append((time.monotonic(), phase)))
            heartbeat.start(50)
            try:
                wait_until(lambda: getattr(pet, '_speech_controller', None) is not None)
                controller = pet._speech_controller
                statuses = []
                controller.status.connect(statuses.append)
                wait_until(lambda: controller.ready, 180, lambda: controller.status_text)
                result['preheat_seconds'] = round(time.monotonic() - started, 3)
                pid = controller.process.processId()
                assert pid > 0 and pid != os.getpid()
                assert getattr(pet, 'chat_window', None) is None
                wait_until(lambda: controller.player.is_ready, 60, lambda: controller.status_text)
                # Native Windows endpoint discovery happens in the separate audio process.
                assert not isinstance(controller.player.player, QMediaPlayer)
                assert 'torch' not in sys.modules
                phase = 'open chat'
                print('Startup warmup seconds:', result['preheat_seconds'], flush=True)
                pet.open_chat()
                chat = pet.chat_window
                chat.config = ProviderConfig(base_url=f'http://127.0.0.1:{server.server_port}/v1',
                                             model='local-speech-fixture', stream=False)
                chat.tabs.setCurrentIndex(0)
                assert controller is chat.speech and controller.process.processId() == pid
                assert chat.speech_toggle.isChecked() and '已就绪' in chat.speech_status.text()
                paths = chat.speech_paths()
                assert all(Path(path).exists() for path in paths), 'Local voice configuration missing'
                plays = []
                original_play = controller.player.play

                def track_play(ticket, path):
                    with wave.open(str(path), 'rb') as wav:
                        details = dict(rate=wav.getframerate(), frames=wav.getnframes(),
                                       seconds=wav.getnframes() / wav.getframerate())
                    success = original_play(ticket, path)
                    if success:
                        plays.append((time.monotonic(), details))
                    return success

                controller.player.play = track_play
                for index, message in enumerate(('今天你好呀', '谢谢你陪我')):
                    phase = f'chat turn {index + 1}'
                    began = time.monotonic()
                    chat.input.setPlainText(message)
                    chat.send_message()
                    wait_until(lambda: controller.active is not None, 20, lambda: chat.status.text())
                    expected = Handler.replies[index].removeprefix('[开心]')
                    assert expected not in chat.history_view.toPlainText()
                    assert len(chat.store.history(chat.character)) == index * 2
                    wait_until(lambda: len(plays) == index + 1, 180, lambda: str(statuses[-3:]))
                    wait_until(lambda: controller.player.player.playbackState()
                               == QMediaPlayer.PlaybackState.PlayingState,
                               10, lambda: controller.player.player.errorString())
                    at, details = plays[-1]
                    assert chat.store.history(chat.character)[-1]['content'] == expected
                    assert expected in chat.history_view.toPlainText()
                    details['seconds_to_playback'] = round(at - began, 3)
                    result['replies'].append(details)
                    assert controller.process.processId() == pid, 'Warm model was unnecessarily restarted'
                    wait_until(lambda: controller.player.player.playbackState()
                               == QMediaPlayer.PlaybackState.StoppedState, 30)
                assert Handler.count == 2 and len(chat.store.history(chat.character)) == 4
                assert '[开心]' not in chat.store.history(chat.character)[1]['content']
                phase = 'proactive turn'
                chat.close()
                runtime = chat.companion_runtime
                runtime.set_chat_enabled(True)
                # Simulate elapsed idle time; generation and actual delivery still run normally.
                with patch.object(runtime, 'state', return_value=CompanionState(idle_seconds=120)), \
                        patch.object(pet.bubble, 'say', wraps=pet.bubble.say) as bubble:
                    runtime.tick()
                    wait_until(lambda: controller.active is not None, 20, lambda: controller.status_text)
                    assert not chat.store.last_proactive(chat.character)
                    bubble.assert_not_called()
                    wait_until(lambda: len(plays) == 3, 180, lambda: controller.status_text)
                    assert chat.store.last_proactive(chat.character) == Handler.replies[2]
                    assert any(call.args[0] == Handler.replies[2] for call in bubble.call_args_list)
                assert Handler.count == 3 and controller.process.processId() == pid
                result['device'] = controller.player.audio.device().description()
                runtime.set_chat_enabled(False)
                chat.show_chat()
                phase = 'cancel and rewarm'
                chat.preview_speech()
                chat.stop_speech()
                wait_until(lambda: controller.process.state() == QProcess.ProcessState.NotRunning, 10)
                QTest.qWait(300)
                assert len(plays) == 3 and controller.active is None
                assert controller.player.player.source().isEmpty(), 'Stopped media source still held open'
                # Preparing again after an explicit stop must work without reopening the window.
                chat.speech_toggle.setChecked(False)
                chat.speech_toggle.setChecked(True)
                wait_until(lambda: controller.warming and controller.process.processId() != 0)
                next_pid = controller.process.processId()
                chat.close()
                wait_until(lambda: controller.ready, 180, lambda: str(statuses[-3:]))
                chat.show_chat()
                assert controller.process.processId() == next_pid
                chat.speech_toggle.setChecked(False)
                wait_until(lambda: controller.process.state() == QProcess.ProcessState.NotRunning, 10)
                assert not list((Path(temp) / 'chat' / 'speech').glob('speech-*.wav'))
                gaps = [(b - a, after) for (a, before), (b, after) in zip(ticks, ticks[1:])]
                worst, phase_of_worst = max(gaps, default=(0, 'none'))
                result.update(passed=True, same_worker_reused=True, cancel_verified=True,
                              restart_verified=True, temporary_wavs_removed=True,
                              proactive_verified=True, worst_gap_phase=phase_of_worst,
                              max_ui_heartbeat_gap_seconds=round(worst, 3))
                assert worst < 3, f'UI heartbeat gap {worst:.3f}s during {phase_of_worst}'
            finally:
                heartbeat.stop()
                if chat is not None:
                    chat.shutdown()
                    chat.hide()
                pet.timer.stop()
                pet.panel.progress_timer.stop()
                pet.panel.bilibili.shutdown()
                pet.panel.shutdown_audio()
                pet.close_live2d()
                pet.tray.hide()
                pet.panel.store.close()
                pet.hide()
                QTest.qWait(50)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
