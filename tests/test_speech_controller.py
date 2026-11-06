import json
import tempfile
import sys
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QObject, Signal
from deskpet.chat.window import ChatWindow


class Router(QObject):
    changed = Signal()
    preferred = ''


class FakePlayer(QObject):
    finished = Signal()
    failed = Signal(str)
    ready = Signal()
    def __init__(self, *args, **kwargs): super().__init__(); self.enabled = False; self.generation = 0; self.played = []; self.is_ready = True; self.audio_failed = False
    def set_enabled(self, value): self.enabled = value
    def prepare(self): pass
    def stop(self): self.generation += 1
    def begin(self): self.stop(); return self.generation
    def play(self, ticket, path): self.played.append((ticket, path)); return True
    def close(self): pass


class SpeechControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        from deskpet.speech.controller import SpeechController
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch('deskpet.speech.controller.SpeechPlayer', FakePlayer):
            self.controller = SpeechController(Router(), self.temp.name)
        self.addCleanup(self.controller.shutdown)
        self.controller.set_enabled(True)

    def feed(self, event):
        raw = ('TIANYI_SPEECH ' + json.dumps(event) + '\n').encode()
        with patch.object(self.controller.process, 'readAllStandardOutput', return_value=raw):
            self.controller._read()

    def make_wav(self, path):
        with wave.open(str(path), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x01\x00" * 10)

    def test_old_result_is_ignored_and_current_result_plays(self):
        c = self.controller
        c.active, c.output = 10, Path(self.temp.name) / 'current.wav'
        self.make_wav(c.output)
        self.feed(dict(type='completed', id=9, path=str(c.output)))
        self.assertEqual(c.player.played, [])
        self.feed(dict(type='completed', id=10, path=str(c.output)))
        self.assertEqual(len(c.player.played), 1)
        self.feed(dict(type='completed', id=10, path=str(c.output)))
        self.assertEqual(len(c.player.played), 1)

    def test_playback_completion_removes_output(self):
        c = self.controller
        c.active, c.output = 10, Path(self.temp.name) / 'current.wav'
        self.make_wav(c.output)
        path = c.output
        self.feed(dict(type='completed', id=10, path=str(path)))
        self.assertTrue(path.exists())
        c.player.finished.emit()
        self.assertFalse(path.exists())
        self.assertIsNone(c.output)

    def test_late_playback_event_preserves_new_synthesis_and_error_reported(self):
        c = self.controller
        c.active, c.output = 11, Path(self.temp.name) / 'new.wav'
        c.output.write_bytes(b'new')
        messages = []
        c.status.connect(messages.append)
        c.player.finished.emit()
        self.assertTrue(c.output.exists())
        c.player.failed.emit('device unavailable')
        self.assertIn('device unavailable', messages[-1])

    def test_delivery_success_failure_and_cancellation(self):
        c = self.controller
        root = Path(self.temp.name)
        config = root / 'config.json'
        config.write_text('{}')
        c.configure(sys.executable, root, config)
        calls = []
        with patch.object(c, '_start'):
            self.assertTrue(c.speak('first', deliver=lambda: calls.append('old') or True))
            self.assertTrue(c.speak('second', deliver=lambda: calls.append('new') or True))
            ticket, path = c.active, c.output
            self.make_wav(path)
            self.feed(dict(type='completed', id=ticket, path=str(path)))
            self.assertEqual(calls, ['new'])
            self.assertEqual(c.player.played[-1], (ticket, path))
            self.assertTrue(c.speak('third', deliver=lambda: calls.append('failure') or True))
            self.feed(dict(type='failed', id=c.active, message='error'))
            self.assertEqual(calls, ['new', 'failure'])
            self.assertTrue(c.speak('fourth', deliver=lambda: calls.append('cancelled') or True))
            c.stop()
            self.assertEqual(calls, ['new', 'failure'])
            self.assertFalse(c.speak('x' * 1001, deliver=lambda: True))

    def test_delivery_waits_for_audio_and_cancel_invalidates_it(self):
        c = self.controller
        root = Path(self.temp.name)
        config = root / 'config.json'
        config.write_text('{}')
        c.configure(sys.executable, root, config)
        c.player.is_ready = False
        calls = []
        with patch.object(c, '_start'):
            self.assertTrue(c.speak('first', deliver=lambda: calls.append('old')))
            path = c.output
            self.make_wav(path)
            self.feed(dict(type='completed', id=c.active, path=str(path)))
            self.assertFalse(calls)
            self.assertFalse(c.player.played)
            c.stop()
            c.player.is_ready = True
            c.player.ready.emit()
            self.assertFalse(calls)
            self.assertFalse(c.player.played)
            c.player.is_ready = False
            self.assertTrue(c.speak('second', deliver=lambda: calls.append('new')))
            path = c.output
            self.make_wav(path)
            self.feed(dict(type='completed', id=c.active, path=str(path)))
            c.player.is_ready = True
            c.player.ready.emit()
            self.assertEqual(calls, ['new'])
            self.assertEqual(len(c.player.played), 1)

    def test_delivery_false_prevents_playback(self):
        c = self.controller
        c.active, c.output = 42, Path(self.temp.name) / 'current.wav'
        c.delivery = lambda: False
        self.make_wav(c.output)
        self.feed(dict(type='completed', id=42, path=str(c.output)))
        self.assertFalse(c.player.played)
        self.assertIsNone(c.output)

    def test_stop_and_failure_discard_pending(self):
        c = self.controller
        c.active, c.output = 3, Path(self.temp.name) / 'old.wav'
        c.stop()
        self.feed(dict(type='completed', id=3, path=str(Path(self.temp.name) / 'old.wav')))
        self.assertFalse(c.player.played)
        messages = []
        c.status.connect(messages.append)
        c.active = 4
        self.feed(dict(type='failed', id=4, message='engine unavailable'))
        self.assertIsNone(c.active)
        self.assertIn('engine unavailable', messages[-1])

    def test_killed_process_late_ready_and_fatal_cannot_steal_new_job(self):
        from PySide6.QtCore import QProcess
        c = self.controller
        root = Path(self.temp.name)
        fake_worker = root / 'fake_worker.py'
        marker = root / 'received.json'
        fake_worker.write_text("import sys,json,time,pathlib\nprint('TIANYI_SPEECH {\"type\":\"ready\"}',flush=True)\nline=sys.stdin.readline()\npathlib.Path(sys.argv[1]).write_text(line,encoding='utf-8')\ntime.sleep(20)\n", encoding='utf-8')
        config = root / 'config.json'
        config.write_text('{}', encoding='utf-8')
        c.configure(sys.executable, root, config)
        def start_fake():
            if not c.queued or c.closing or c.terminating:
                return
            c.ready = False
            c.buffer = b''
            c.process.setProgram(sys.executable)
            c.process.setArguments([str(fake_worker), str(marker)])
            c.process.start()
        c._start = start_fake
        self.assertTrue(c.speak('old'))
        self.assertTrue(c.process.waitForStarted(3000))
        old_pid = c.process.processId()
        self.assertTrue(c.speak('new'))
        new_id = c.active
        self.assertTrue(c.terminating)
        self.feed(dict(type='ready'))
        self.feed(dict(type='fatal', message='old failure'))
        self.assertEqual(c.queued['id'], new_id)
        self.assertEqual(c.active, new_id)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not marker.exists():
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(marker.exists(), 'replacement worker did not receive job')
        self.assertNotEqual(c.process.processId(), old_pid)
        self.assertEqual(json.loads(marker.read_text(encoding='utf-8'))['text'], 'new')
        self.assertEqual(c.active, new_id)
        self.assertIsNone(c.queued)
        c.shutdown()
        c.shutdown()  # Repeated shutdown must be harmless.

    def test_disabling_unloads_idle_worker(self):
        from PySide6.QtCore import QProcess
        c = self.controller
        c.process.setProgram(sys.executable)
        c.process.setArguments(['-c', 'import time; time.sleep(20)'])
        c.process.start()
        self.assertTrue(c.process.waitForStarted(3000))
        c.ready = True
        c.active = None
        c.set_enabled(False)
        self.assertTrue(c.terminating)
        self.assertTrue(c.process.waitForFinished(3000))
        self.assertEqual(c.process.state(), QProcess.ProcessState.NotRunning)

    def test_unexpected_exit_never_restarts_queued_job(self):
        c = self.controller
        c.active = 12
        c.queued = {'id': 12}
        c.terminating = False
        messages = []
        c.status.connect(messages.append)
        with patch.object(c, '_start') as start:
            c._finished()
        start.assert_not_called()
        self.assertIsNone(c.active)
        self.assertIsNone(c.queued)
        self.assertIn('已退出', messages[-1])

    def test_ready_status_requires_model_and_audio(self):
        c = self.controller
        messages = []
        c.status.connect(messages.append)
        c.player.is_ready = False
        self.feed(dict(type='ready'))
        self.assertFalse(any('语音已就绪' in message for message in messages))
        c.player.is_ready = True
        c.player.ready.emit()
        self.assertIn('语音已就绪', messages[-1])

    def test_prewarm_accepts_reply_without_restarting_or_playing(self):
        from PySide6.QtCore import QProcess
        c = self.controller
        c.set_enabled(False)
        root = Path(self.temp.name)
        config, received = root / 'config.json', root / 'received.json'
        config.write_text('{}', encoding='utf8')
        script = root / 'warm.py'
        script.write_text("import sys,time,pathlib\ntime.sleep(.4)\nprint('TIANYI_SPEECH {\"type\":\"ready\"}', flush=True)\nline=sys.stdin.buffer.readline()\npathlib.Path(sys.argv[1]).write_bytes(line)\ntime.sleep(20)\n", encoding='utf8')
        c.configure(sys.executable, root, config)
        launches = []
        def start_fake():
            launches.append(1)
            c.process.setProgram(sys.executable)
            c.process.setArguments([str(script), str(received)])
            c.process.start()
        c._start = start_fake
        self.app.processEvents()
        self.assertEqual(launches, [])
        messages=[]
        c.status.connect(messages.append)
        c.set_enabled(True)
        self.app.processEvents()
        self.assertTrue(c.process.waitForStarted(3000))
        pid = c.process.processId()
        self.assertEqual(len(launches), 1)
        self.assertTrue(c.speak('真实回复'))
        self.assertEqual(c.process.processId(), pid)
        self.assertFalse(c.terminating)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not received.exists():
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(received.exists())
        self.assertEqual(json.loads(received.read_text(encoding='utf8'))['text'], '真实回复')
        self.assertEqual(len(launches), 1)
        self.assertFalse(c.player.played)
        self.assertTrue(any('语音已就绪' in value for value in messages))

    def test_stop_before_deferred_prewarm_prevents_launch(self):
        c = self.controller
        c.set_enabled(False)
        root = Path(self.temp.name)
        config = root / 'config.json'
        config.write_text('{}', encoding='utf8')
        c.configure(sys.executable, root, config)
        with patch.object(c, '_start') as start:
            c.set_enabled(True)
            c.stop()
            self.app.processEvents()
        start.assert_not_called()

    def test_warm_crash_does_not_restart_and_is_reported(self):
        c = self.controller
        c.warming = True
        c.active = c.queued = None
        messages=[]
        c.status.connect(messages.append)
        with patch.object(c, '_start') as start:
            c._finished()
        start.assert_not_called()
        self.assertFalse(c.warming)
        self.assertTrue(any('已退出' in value for value in messages))

    def test_work_mode_and_other_characters_never_speak(self):
        calls=[]; statuses=[]
        fake = SimpleNamespace(speech_toggle=SimpleNamespace(isChecked=lambda: True),
                               companion_mode_enabled=False, character='builtin:luotianyi',
                               speech=SimpleNamespace(speak=calls.append),
                               status=SimpleNamespace(setText=statuses.append))
        ChatWindow.say_reply(fake, 'message')
        fake.companion_mode_enabled=True; fake.character='other'
        ChatWindow.say_reply(fake, 'message')
        self.assertEqual(calls, [])
        self.assertIn('未配置语音', statuses[-1])
        fake.character='builtin:luotianyi'
        ChatWindow.say_reply(fake, 'message')
        self.assertEqual(calls, ['message'])


if __name__ == '__main__': unittest.main()
