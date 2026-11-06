import tempfile
import unittest
import wave
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Signal
from deskpet.music.audio.routing import device_id
from deskpet.speech.player import SpeechPlayer, valid_wav


class Device:
    def __init__(self, name): self.name = name
    def id(self): return self.name.encode()
    def isNull(self): return not self.name


class Devices(QObject):
    audioOutputsChanged = Signal()
    def __init__(self, outputs, default):
        super().__init__()
        self.outputs, self.default = outputs, default
    def audioOutputs(self): return self.outputs
    def defaultAudioOutput(self): return self.default


class Router(QObject):
    changed = Signal()
    def __init__(self):
        super().__init__()
        self.preferred = ''


class Audio:
    def __init__(self, device): self.current = device
    def device(self): return self.current
    def setDevice(self, device): self.current = device


class Player(QObject):
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)
    def __init__(self): super().__init__(); self.plays, self.stops, self.sources = 0, 0, []
    def setAudioOutput(self, audio): self.audio = audio
    def setSource(self, url): self.sources.append(url)
    def play(self): self.plays += 1
    def stop(self): self.stops += 1


class SpeechTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.wav = Path(self.temp.name) / 'voice.wav'
        with wave.open(str(self.wav), 'wb') as sound:
            sound.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            sound.writeframes(b'\x01\x00' * 50)
        self.a, self.b = Device('speaker'), Device('headset')
        self.devices, self.router = Devices([self.a, self.b], self.a), Router()
        self.audio, self.player = Audio(self.a), Player()
        self.speech = SpeechPlayer(self.router, player=self.player, audio=self.audio, devices=self.devices)
        self.addCleanup(self.speech.close)
        self.speech.set_enabled(True)

    def test_only_latest_pending_ticket_plays_once(self):
        old = self.speech.begin()
        current = self.speech.begin()
        self.assertFalse(self.speech.play(old, self.wav))
        self.assertTrue(self.speech.play(current, self.wav))
        self.assertFalse(self.speech.play(current, self.wav))
        self.assertEqual(self.player.plays, 1)
        current = self.speech.begin()
        self.speech.stop()
        self.assertFalse(self.speech.play(current, self.wav))
        current = self.speech.begin()
        self.speech.set_enabled(False)
        self.assertFalse(self.speech.play(current, self.wav))
        self.assertIsNone(self.speech.begin())

    def test_maps_preferred_and_follows_default_and_reconnect(self):
        self.router.preferred = device_id(self.b)
        self.router.changed.emit()
        self.assertIs(self.audio.current, self.b)
        self.devices.outputs = [self.a]
        self.devices.audioOutputsChanged.emit()
        self.assertIs(self.audio.current, self.a)
        self.devices.outputs.append(self.b)
        self.devices.audioOutputsChanged.emit()
        self.assertIs(self.audio.current, self.b)
        self.router.preferred = ''
        self.router.changed.emit()
        self.assertIs(self.audio.current, self.a)
        self.devices.default = self.b
        self.devices.audioOutputsChanged.emit()
        self.assertIs(self.audio.current, self.b)

    def test_late_music_router_is_bound_and_replaced(self):
        slot = [None]
        other_audio = Audio(self.a)
        other = SpeechPlayer(lambda: slot[0], player=Player(), audio=other_audio, devices=self.devices)
        self.addCleanup(other.close)
        self.assertIs(other_audio.current, self.a)
        late = Router()
        late.preferred = device_id(self.b)
        slot[0] = late
        other.refresh_output()  # The 500 ms poll performs the same check.
        self.assertIs(other_audio.current, self.b)
        late.preferred = ''
        late.changed.emit()
        self.assertIs(other_audio.current, self.a)
        replacement = Router()
        replacement.preferred = device_id(self.b)
        slot[0] = replacement
        other.refresh_output()
        self.assertIs(other_audio.current, self.b)
        late.changed.emit()
        self.assertIs(other_audio.current, self.b)

    def test_saved_preference_applies_before_music_router_exists(self):
        slot = [None]
        other_audio = Audio(self.a)
        other = SpeechPlayer(lambda: slot[0], player=Player(), audio=other_audio,
                             devices=self.devices, preferred_getter=lambda: device_id(self.b))
        self.addCleanup(other.close)
        self.assertIs(other_audio.current, self.b)
        self.devices.outputs = [self.a]
        self.devices.audioOutputsChanged.emit()
        self.assertIs(other_audio.current, self.a)
        self.devices.outputs.append(self.b)
        self.devices.audioOutputsChanged.emit()
        self.assertIs(other_audio.current, self.b)
        router = Router()
        router.preferred = ''
        slot[0] = router
        other.refresh_output()
        self.assertIs(other_audio.current, self.a)

    def test_playback_completion_and_error_release_source(self):
        from PySide6.QtMultimedia import QMediaPlayer
        finished = []
        errors = []
        self.speech.failed.connect(errors.append)
        self.speech.finished.connect(lambda: finished.append(True))
        self.assertTrue(self.speech.play(self.speech.begin(), self.wav))
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertTrue(self.player.sources[-1].isEmpty())
        self.assertEqual(len(finished), 1)
        self.assertTrue(self.speech.play(self.speech.begin(), self.wav))
        self.player.errorOccurred.emit(QMediaPlayer.Error.ResourceError, 'error')
        self.assertTrue(self.player.sources[-1].isEmpty())
        self.assertEqual(len(finished), 2)
        self.assertEqual(errors, ['error'])
        self.speech.stop()
        self.player.errorOccurred.emit(QMediaPlayer.Error.ResourceError, 'late')
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(len(finished), 2)
        self.assertEqual(errors, ['error'])

    def test_stop_releases_source_and_close_is_idempotent(self):
        ticket = self.speech.begin()
        self.assertTrue(self.speech.play(ticket, self.wav))
        self.assertFalse(self.player.sources[-1].isEmpty())
        self.speech.stop()
        self.assertTrue(self.player.sources[-1].isEmpty())
        self.speech.close()
        self.speech.close()

    def test_invalid_empty_and_truncated_wav_are_rejected(self):
        self.assertTrue(valid_wav(self.wav))
        empty = Path(self.temp.name) / 'empty.wav'
        with wave.open(str(empty), 'wb') as sound:
            sound.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        broken = Path(self.temp.name) / 'broken.wav'
        broken.write_bytes(self.wav.read_bytes()[:-3])
        for path in (empty, broken, Path(self.temp.name) / 'missing.wav'):
            self.assertFalse(valid_wav(path))
            self.assertFalse(self.speech.play(self.speech.begin(), path))
        self.assertEqual(self.player.plays, 0)


if __name__ == '__main__': unittest.main()
