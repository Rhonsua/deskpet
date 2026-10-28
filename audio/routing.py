"""Follow the default output or a saved headset across device changes."""
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtMultimedia import QMediaDevices


def device_id(device):
    return bytes(device.id()).hex() if not device.isNull() else ''


def resolve_output(preferred, outputs, default):
    """Keep a missing preference so reconnecting the headset restores it."""
    if preferred:
        match = next((device for device in outputs if device_id(device) == preferred), None)
        if match is not None:
            return match, False
    return default, bool(preferred)


class AudioRouter(QObject):
    changed = Signal()
    routeWillChange = Signal()
    routeChanged = Signal()

    def __init__(self, audio, settings, parent=None, devices=None):
        super().__init__(parent)
        self.audio = audio
        self.settings = settings
        self.devices = devices if devices is not None else QMediaDevices(self)
        self.preferred = settings.value('audio_output_id', '')
        self.outputs = []
        self.default = None
        self.fallback = False
        self.summary = ''
        self.signature = None
        self.devices.audioOutputsChanged.connect(self.refresh)
        # Some Windows drivers notify late when only the default endpoint changes.
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()

    def choose(self, identifier):
        self.preferred = identifier or ''
        self.settings.setValue('audio_output_id', self.preferred)
        name = next((device.description() for device in self.outputs
                     if device_id(device) == self.preferred), '')
        self.settings.setValue('audio_output_name', name)
        self.refresh()

    def refresh(self):
        self.outputs = list(self.devices.audioOutputs())
        self.default = self.devices.defaultAudioOutput()
        target, self.fallback = resolve_output(self.preferred, self.outputs, self.default)
        actual_id = device_id(target)
        if device_id(self.audio.device()) != actual_id:
            self.routeWillChange.emit()
            self.audio.setDevice(target)
            self.routeChanged.emit()
        name = target.description() if not target.isNull() else '暂无可用输出设备'
        if self.fallback:
            self.summary = '所选设备未连接，暂用：' + name
        elif self.preferred:
            self.summary = '当前输出：' + name
        else:
            self.summary = '跟随系统：' + name
        signature = (tuple((device_id(d), d.description()) for d in self.outputs),
                     device_id(self.default), self.preferred, self.summary)
        if signature != self.signature:
            self.signature = signature
            self.changed.emit()
