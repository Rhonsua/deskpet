"""Play completed local WAV files without taking ownership of music playback.

All methods belong to the Qt thread that created the player. A renderer should
return its result to that thread and pass the ticket obtained from begin().
"""
from pathlib import Path
import wave

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer
from deskpet.music.audio.remote import AudioEngine

from deskpet.music.audio.routing import device_id, resolve_output


def valid_wav(path):
    """Accept nonempty, complete uncompressed PCM WAV data only."""
    try:
        with wave.open(str(path), 'rb') as sound:
            frames = sound.getnframes()
            channels, width, rate = sound.getnchannels(), sound.getsampwidth(), sound.getframerate()
            if not frames or not channels or width not in (1, 2, 3, 4) or not rate or sound.getcomptype() != 'NONE':
                return False
            sound.setpos(frames - 1)
            return len(sound.readframes(1)) == channels * width
    except (OSError, EOFError, ValueError, wave.Error, TypeError):
        return False


class DefaultRouter(QObject):
    changed = Signal()
    preferred = ''


class SpeechPlayer(QObject):
    """Play one result per ticket. The caller owns synthesis and WAV lifetime."""

    finished = Signal()
    failed = Signal(str)
    ready = Signal()

    def __init__(self, music_router, parent=None, *, player=None, audio=None, devices=None, preferred_getter=None):
        super().__init__(parent)
        self.router_getter = music_router if callable(music_router) else lambda: music_router
        self.preferred_getter = preferred_getter or (lambda: '')
        self.fallback_router = DefaultRouter(self)
        self.router = None
        self.closed = False
        self.audio, self.player, self.devices = audio, player, devices
        self.engine = None
        self.retiring = []
        self.is_ready = player is not None
        self.audio_failed = False
        self.volume = None
        self.enabled = False
        self.generation = 0
        self.pending = None
        self.playing = False
        # Windows can change the default without a timely device signal.
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.refresh_output)
        if self.player is not None:
            self._connect_media()

    def _connect_media(self):
        if self.volume is not None:
            self.audio.setVolume(self.volume)
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._playback_error)
        self.devices.audioOutputsChanged.connect(self.refresh_output)
        self.refresh_output()

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, float(value)))
        if self.audio is not None:
            self.audio.setVolume(self.volume)

    def refresh_output(self):
        if self.closed:
            return
        if self.engine is not None:
            router = self.router_getter() or self.fallback_router
            if router is not self.router:
                if self.router is not None:
                    self.router.changed.disconnect(self.refresh_output)
                self.router = router
                self.router.changed.connect(self.refresh_output)
            preferred = (self.preferred_getter() or '') if router is self.fallback_router else router.preferred
            if preferred != getattr(self, '_last_preferred', None):
                self._last_preferred = preferred
                self.engine.router.choose(preferred)
            return
        if self.devices is None:
            return
        router = self.router_getter() or self.fallback_router
        if router is not self.router:
            if self.router is not None:
                self.router.changed.disconnect(self.refresh_output)
            self.router = router
            self.router.changed.connect(self.refresh_output)
        preferred = self.preferred_getter() or '' if self.router is self.fallback_router else self.router.preferred
        target, _ = resolve_output(preferred, list(self.devices.audioOutputs()),
                                   self.devices.defaultAudioOutput())
        if device_id(self.audio.device()) != device_id(target):
            self.audio.setDevice(target)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()
            self._shutdown_engine()

    def prepare(self):
        if self.enabled and self.player is None and self.engine is None:
            try:
                self._start_engine()
            except OSError:
                self._shutdown_engine()
                self._engine_failed('无法创建临时音频配置，请检查临时文件夹权限和磁盘空间。')

    def _start_engine(self):
        # The helper owns native multimedia objects and an isolated routing settings copy.
        from tempfile import TemporaryDirectory
        class Settings:
            def __init__(self, preferred): self.values = {'audio_output_id': preferred}
            def value(self, key, default=''): return self.values.get(key, default)
            def setValue(self, key, value): self.values[key] = value
        self.audio_failed = False
        self._engine_dir = TemporaryDirectory(prefix='tianyi-speech-audio-')
        router = self.router_getter() or self.fallback_router
        preferred = (self.preferred_getter() or '') if router is self.fallback_router else router.preferred
        self.engine = AudioEngine(Settings(preferred), self._engine_dir.name, self)
        self.player, self.audio = self.engine.player, self.engine.audio
        engine = self.engine
        engine.player.mediaStatusChanged.connect(lambda status: self._media_status(status) if self.engine is engine else None)
        engine.player.errorOccurred.connect(lambda error, message: self._playback_error(error, message) if self.engine is engine else None)
        engine.loadingChanged.connect(lambda loading: self._loading_changed(loading) if self.engine is engine else None)
        engine.failed.connect(lambda message: self._engine_failed(message) if self.engine is engine else None)
        if self.volume is not None: self.audio.setVolume(self.volume)
        self._last_preferred = None
        self.refresh_output()
        self.poll.start()
        self.engine.start()

    def _loading_changed(self, loading):
        if (not loading and self.engine is not None and self.engine.ready
                and self.engine.process.state() == self.engine.process.ProcessState.Running):
            self.is_ready = True
            self.ready.emit()

    def _engine_failed(self, message):
        self.is_ready = False
        self.audio_failed = True
        self.failed.emit(message)

    def _shutdown_engine(self):
        if self.engine is None:
            return
        engine, self.engine = self.engine, None
        temp, self._engine_dir = self._engine_dir, None
        self.is_ready = False
        self.player = self.audio = None
        if self.router is not None:
            self.router.changed.disconnect(self.refresh_output)
            self.router = None
        self.poll.stop()
        engine.closing = True
        self.retiring.append((engine, temp))
        def retire(*_):
            if (engine, temp) in self.retiring:
                self.retiring.remove((engine, temp))
                temp.cleanup()
                engine.deleteLater()
        engine.process.finished.connect(retire)
        if engine.process.state() == engine.process.ProcessState.NotRunning:
            retire()
        else:
            engine.write({'cmd': 'close'})
            QTimer.singleShot(1500, lambda: engine.process.kill() if (engine, temp) in self.retiring else None)

    def begin(self):
        """Invalidate old work and return a ticket, or None when disabled."""
        self.stop()
        if not self.enabled:
            return None
        self.pending = self.generation
        return self.pending

    def play(self, ticket, path):
        """Play a valid WAV for the current ticket; reject stale results."""
        if not self.enabled or not self.is_ready or ticket is None or ticket != self.pending:
            return False
        self.pending = None
        if not valid_wav(path):
            return False
        self.refresh_output()
        self.poll.start()
        self.playing = True
        self.player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.player.play()
        return True

    def _media_status(self, status):
        if self.playing and status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playing = False
            self.player.setSource(QUrl())
            self.finished.emit()

    def _playback_error(self, error, message):
        if not self.playing:
            return
        self.playing = False
        self.player.setSource(QUrl())
        self.finished.emit()
        self.failed.emit(message)

    def stop(self):
        """Stop playback and invalidate any result still being synthesized."""
        self.generation += 1
        self.pending = None
        self.playing = False
        if self.player is not None and (self.engine is None or self.engine.ready):
            self.player.stop()
            self.player.setSource(QUrl())

    def close(self):
        if self.closed:
            return
        self.stop()
        self._shutdown_engine()
        for engine, temp in list(self.retiring):
            if not engine.process.waitForFinished(1500):
                engine.process.kill()
                engine.process.waitForFinished(1000)
        self.closed = True
        self.poll.stop()
        if self.router is not None:
            self.router.changed.disconnect(self.refresh_output)
        if self.devices is not None:
            self.devices.audioOutputsChanged.disconnect(self.refresh_output)
