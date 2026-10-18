"""Small Qt-compatible proxies for an isolated native audio helper."""
import json
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from worker_command import worker_command


class Device:
    def __init__(self, data=None):
        self.data = data or {}

    def id(self):
        return bytes.fromhex(self.data.get('id', ''))

    def description(self):
        return self.data.get('name', '')

    def isNull(self):
        return not self.data.get('id')


class RemoteOutput(QObject):
    def __init__(self, engine):
        super().__init__(engine)
        self.engine = engine
        self.value = .6
        self.muted = False
        self.target = Device()

    def volume(self): return self.value
    def isMuted(self): return self.muted
    def device(self): return self.target

    def setVolume(self, value):
        self.value = float(value)
        self.engine.send({'cmd': 'volume', 'value': self.value})

    def setMuted(self, value):
        self.muted = bool(value)
        self.engine.send({'cmd': 'muted', 'value': self.muted})


class RemoteRouter(QObject):
    changed = Signal()

    def __init__(self, engine):
        super().__init__(engine)
        self.engine = engine
        self.outputs, self.default = [], Device()
        self.preferred = ''
        self.summary = '正在准备音频设备…'
        self.fallback = False
        self.signature = None
        self.poll = QTimer(self)  # Compatibility; actual polling lives in the helper.

    def choose(self, identifier):
        self.engine.send({'cmd': 'output', 'id': identifier or ''})

    def refresh(self): pass


class RemotePlayer(QObject):
    PlaybackState = QMediaPlayer.PlaybackState
    MediaStatus = QMediaPlayer.MediaStatus
    Error = QMediaPlayer.Error
    durationChanged = Signal(int)
    seekableChanged = Signal(bool)
    positionChanged = Signal(int)
    playbackStateChanged = Signal(object)
    mediaStatusChanged = Signal(object)
    errorOccurred = Signal(object, str)

    def __init__(self, engine):
        super().__init__(engine)
        self.engine = engine
        self.url = QUrl()
        self.values = {'position': 0, 'duration': 0, 'state': 0, 'status': 0, 'seekable': False,
                       'error': 0, 'error_text': ''}

    def source(self): return self.url
    def position(self): return self.values['position']
    def duration(self): return self.values['duration']
    def playbackState(self): return QMediaPlayer.PlaybackState(self.values['state'])
    def mediaStatus(self): return QMediaPlayer.MediaStatus(self.values['status'])
    def isSeekable(self): return self.values['seekable']
    def errorString(self): return self.values['error_text']
    def error(self): return QMediaPlayer.Error(self.values['error'])

    def setSource(self, url):
        self.url = QUrl(url)
        self.engine.generation += 1
        self.values.update(position=0, duration=0, status=0, seekable=False, error=0, error_text='')
        self.engine.send({'cmd': 'source', 'url': url.toString(), 'generation': self.engine.generation})

    def play(self): self.engine.send({'cmd': 'play'})
    def pause(self): self.engine.send({'cmd': 'pause'})
    def stop(self): self.engine.send({'cmd': 'stop'})
    def setPosition(self, position): self.engine.send({'cmd': 'seek', 'position': position})


class AudioEngine(QObject):
    loadingChanged = Signal(bool)
    failed = Signal(str)

    def __init__(self, settings, data_dir, parent=None):
        super().__init__(parent)
        self.ready = self.closing = False
        self.generation = 0
        self.pending, self.buffer = [], ''
        self.player = RemotePlayer(self)
        self.audio = RemoteOutput(self)
        self.router = RemoteRouter(self)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_events)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.settings_file = str(Path(data_dir) / 'audio-helper.ini')
        # A separate INI carries only routing preferences, including in registry builds.
        from PySide6.QtCore import QSettings
        routing = QSettings(self.settings_file, QSettings.Format.IniFormat)
        for key in ('audio_output_id', 'audio_output_name'):
            routing.setValue(key, settings.value(key, ''))
        routing.sync()
        self.settings = settings

    def start(self):
        self.closing = False
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('PYTHONUNBUFFERED', '1')
        env.insert('QT_QPA_PLATFORM', 'offscreen')
        self.process.setProcessEnvironment(env)
        program, arguments = worker_command('audio')
        self.process.setProgram(program)
        self.process.setArguments(arguments + ['--settings', self.settings_file])
        self.loadingChanged.emit(True)
        self.process.start()

    def send(self, item):
        if not self.ready:
            self.pending.append(item)
        else:
            self.write(item)

    def write(self, item):
        self.process.write((json.dumps(item) + '\n').encode('utf-8'))

    def read_events(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if not line.startswith('TIANYI_AUDIO '): continue
            try:
                value = json.loads(line[13:])
            except ValueError:
                continue
            if value.get('type') == 'ready':
                self.ready = True
                for item in self.pending: self.write(item)
                self.pending.clear()
                self.loadingChanged.emit(False)
            elif value.get('type') == 'state' and value.get('generation') == self.generation:
                self.update(value)
        self.buffer = self.buffer[-65536:]

    def update(self, value):
        self.audio.target = Device(value['device'])
        self.router.outputs = [Device(item) for item in value['outputs']]
        self.router.default = Device(value['default'])
        signature = (tuple((item['id'], item['name']) for item in value['outputs']),
                     value['default']['id'], value['preferred'], value['fallback'], value['summary'])
        if self.router.signature != signature:
            self.router.signature = signature
            self.router.summary, self.router.preferred = value['summary'], value['preferred']
            self.router.fallback = value['fallback']
            self.settings.setValue('audio_output_id', self.router.preferred)
            if not value['fallback']:
                self.settings.setValue('audio_output_name', self.audio.target.description())
            self.router.changed.emit()
        previous = self.player.values
        self.player.values = value
        generation = self.generation
        for key, signal, transform in (
                ('duration', self.player.durationChanged, int), ('seekable', self.player.seekableChanged, bool),
                ('position', self.player.positionChanged, int),
                ('state', self.player.playbackStateChanged, QMediaPlayer.PlaybackState),
                ('status', self.player.mediaStatusChanged, QMediaPlayer.MediaStatus)):
            if generation != self.generation: return
            if previous[key] != value[key]: signal.emit(transform(value[key]))
        if value['error'] and previous['error'] != value['error']:
            self.player.errorOccurred.emit(QMediaPlayer.Error(value['error']), value['error_text'])

    def process_error(self, *_):
        if self.process.error() == QProcess.ProcessError.FailedToStart:
            self.loadingChanged.emit(False)
            self.failed.emit('音频进程启动失败，请检查安装文件是否完整')

    def finished(self, *_):
        self.loadingChanged.emit(False)
        if not self.closing:
            self.player.values['state'] = 0
            self.player.playbackStateChanged.emit(QMediaPlayer.PlaybackState.StoppedState)
            self.failed.emit('音频进程已退出，请关闭桌宠后重试')

    def shutdown(self):
        self.closing = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.write({'cmd': 'close'})
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)
