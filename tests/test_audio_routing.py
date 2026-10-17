import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QObject, QSettings, Signal
from audio_routing import AudioRouter, device_id


class Device:
    def __init__(self, identifier='', name=''):
        self.identifier, self.name = identifier, name
    def id(self):
        return self.identifier.encode()
    def isNull(self):
        return not self.identifier
    def description(self):
        return self.name


class Devices(QObject):
    audioOutputsChanged = Signal()
    def __init__(self, outputs, default):
        super().__init__()
        self.outputs, self.default = outputs, default
    def audioOutputs(self):
        return self.outputs
    def defaultAudioOutput(self):
        return self.default


class Audio:
    def __init__(self, current):
        self.current, self.calls = current, []
    def device(self):
        return self.current
    def setDevice(self, device):
        self.current = device
        self.calls.append(device_id(device))


class AudioRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.settings = QSettings(str(Path(self.scratch.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.speaker, self.headset = Device('speaker', '扬声器'), Device('bt-headset', '蓝牙耳机')
        self.devices = Devices([self.speaker, self.headset], self.speaker)
        self.audio = Audio(self.speaker)
        self.router = AudioRouter(self.audio, self.settings, devices=self.devices)
        self.addCleanup(self.router.poll.stop)
        self.router.refresh()

    def test_follows_default_changed_while_running(self):
        self.devices.default = self.headset
        self.devices.audioOutputsChanged.emit()
        self.assertEqual(self.audio.current, self.headset)
        self.assertIn('跟随系统', self.router.summary)

    def test_poll_does_not_rebind_unchanged_endpoint(self):
        self.router.refresh()
        self.router.refresh()
        self.assertEqual(self.audio.calls, [])

    def test_explicit_headset_survives_default_change(self):
        self.router.choose(device_id(self.headset))
        self.devices.audioOutputsChanged.emit()
        self.assertEqual(self.audio.current, self.headset)
        self.assertEqual(self.settings.value('audio_output_id'), device_id(self.headset))
        self.assertFalse(self.router.fallback)

    def test_disconnect_falls_back_and_reconnect_restores_headset(self):
        self.router.choose(device_id(self.headset))
        self.devices.outputs = [self.speaker]
        self.devices.audioOutputsChanged.emit()
        self.assertEqual(self.audio.current, self.speaker)
        self.assertTrue(self.router.fallback)
        self.assertEqual(self.router.preferred, device_id(self.headset))
        self.devices.outputs.append(self.headset)
        self.devices.audioOutputsChanged.emit()
        self.assertEqual(self.audio.current, self.headset)
        self.assertFalse(self.router.fallback)

    def test_no_output_and_recovery(self):
        self.devices.outputs, self.devices.default = [], Device()
        self.devices.audioOutputsChanged.emit()
        self.assertTrue(self.audio.current.isNull())
        self.devices.outputs, self.devices.default = [self.headset], self.headset
        self.devices.audioOutputsChanged.emit()
        self.assertEqual(self.audio.current, self.headset)

    def test_saved_preference_is_applied_on_restart(self):
        self.settings.setValue('audio_output_id', device_id(self.headset))
        other = AudioRouter(self.audio, self.settings, devices=self.devices)
        self.addCleanup(lambda owner=other: owner.poll.stop())
        other.refresh()
        self.assertEqual(self.audio.current, self.headset)
        other.choose('')
        self.assertEqual(self.audio.current, self.speaker)


if __name__ == '__main__':
    unittest.main()
