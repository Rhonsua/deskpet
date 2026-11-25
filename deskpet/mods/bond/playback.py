"""An activity's own audio channel, using the audio helper shipped with 0.7.2."""
import time

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QTimer, QUrl, Signal


class ClipPlayer(QObject):
    started = Signal()
    finished = Signal()
    failed = Signal(str)
    progress = Signal(float)
    source_duration = Signal(float)

    def __init__(self, mod, parent):
        super().__init__(parent)
        self.mod = mod
        self.engine = self.token = self.legacy_settings = None
        self.live = self.loaded = self.paused = False
        self.volume = 1.0
        self.elapsed = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)

    def claim(self):
        if not self.mod.active or getattr(self.mod, 'activity_audio_owner', None) is not None:
            return False
        services = self.mod.services
        shared = getattr(services, 'audio_claim_mixed', None)
        if shared:
            self.token = shared()
            if not self.token:
                return False
        else:
            # The released API 3 rejects a lease whenever regular music plays.
            # Our helper mixes independently. Keep the lease when the host offers it.
            self.token = services.audio_claim()
            if not self.token and not services.snapshot()['playing']:
                return False
        self.mod.activity_audio_owner = self
        return True

    def valid(self):
        return (self.mod.active and getattr(self.mod, 'activity_audio_owner', None) is self
                and (not self.token or self.mod.services.audio_valid(self.token)))

    def _read_preferences(self):
        preferences = getattr(self.mod.services, 'audio_preferences', None)
        if preferences:
            return preferences()
        # Released 0.7.2 exposes volume in snapshot and stores the output choice here.
        if self.legacy_settings is None:
            self.legacy_settings = QSettings('TianyiPet', 'Prototype')
        return self.mod.services.snapshot().get('volume', .5), self.legacy_settings.value('audio_output_id', '')

    def _update_output(self):
        self.volume, preferred = self._read_preferences()
        if preferred != self.preferred:
            self.preferred = preferred
            self.engine.router.choose(preferred)
        if abs(self.engine.audio.volume() - self.volume) > .0001:
            self.engine.audio.setVolume(self.volume)
        self.next_preferences = time.monotonic() + 1

    def _prepare_engine(self):
        from deskpet.music.audio.remote import AudioEngine
        # Keep the helper's device observations in Mod storage. The host owns
        # the user's actual choice; a device disconnect in a game must not change it.
        settings = QSettings(str(self.mod.context.data_dir / 'audio-helper.ini'), QSettings.IniFormat)
        self.volume, self.preferred = self._read_preferences()
        settings.setValue('audio_output_id', self.preferred)
        engine = AudioEngine(settings, self.mod.context.data_dir, self)
        self.engine = engine
        engine.player.durationChanged.connect(self._source_duration_changed)
        engine.player.mediaStatusChanged.connect(self._media_status)
        engine.player.errorOccurred.connect(self._media_error)
        engine.failed.connect(self._engine_failed)
        QCoreApplication.instance().aboutToQuit.connect(engine.shutdown)
        engine.audio.setVolume(self.volume)
        engine.start()

    def play(self, path, offset=0., duration=None):
        """An omitted duration plays through the decoder's end-of-media event."""
        self.stop()
        if not self.claim():
            self.failed.emit('另一项互动正在播放，请先结束那项互动，再点重试。')
            return False
        self.offset, self.duration = offset, duration
        self.elapsed = 0.
        self.last_position = -1
        self.last_advance = time.monotonic()
        self.live = True
        self.seek_sent = False
        try:
            if self.engine is None:
                self._prepare_engine()
            self._update_output()
            self.engine.player.setSource(QUrl.fromLocalFile(path))
            self.timer.start()
        except (OSError, RuntimeError, ValueError) as error:
            self._retire_engine()
            self.error(f'无法准备活动音频。{error}')
        return self.live

    def _source_duration_changed(self, milliseconds):
        if (self.live and self.duration is None and milliseconds > 0 and self.engine is not None
                and self.sender() is self.engine.player):
            self.source_duration.emit(milliseconds / 1000)

    def _media_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if not self.live or self.engine is None or self.sender() is not self.engine.player:
            return
        if status == QMediaPlayer.EndOfMedia:
            player = self.engine.player
            elapsed = max(self.elapsed, player.position()/1000 - self.offset)
            if not self.valid():
                self.error('本次互动已结束。')
            elif player.error() != QMediaPlayer.NoError:
                self._media_error(player.error(), player.errorString())
            elif self.duration is None:
                # Very short files can finish between two 100 ms helper reports.
                length = player.position()/1000 or player.duration()/1000
                if self.loaded:
                    # Windows can snap to an estimated MP3 duration on EOF. Keep
                    # the last running clock when that jump exceeds a few reports.
                    since_sample = time.monotonic() - self.last_advance
                    observed_end = self.offset + self.elapsed + since_sample
                    if 0 <= since_sample < .5 and abs(length - observed_end) > .35:
                        length = observed_end
                    length = max(length, self.offset + self.elapsed)
                if self.seek_sent and length > 0:
                    self.source_duration.emit(length)
                    if self.live:
                        self.done()
                else:
                    self.error('没有读到可播放的音频。')
            elif self.loaded and elapsed >= self.duration - .2:
                self.done()
            else:
                self.error('音频提前结束，片段没有播完。')
        elif status == QMediaPlayer.InvalidMedia:
            self._media_error(None, self.engine.player.errorString())

    def _media_error(self, error, message):
        if self.live and self.engine is not None and self.sender() is self.engine.player:
            self.error('音频文件无法播放。' + (str(message)[:180] or '请检查文件是否存在、能否正常打开。'))

    def _engine_failed(self, message):
        if self.sender() is not self.engine:
            return
        self._retire_engine()
        if message == '音频进程已退出，请关闭桌宠后重试':
            message = '活动音频进程已退出，请重试。'
        self.error(message)

    def tick(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if not self.live:
            return
        if not self.valid():
            self.error('本次互动已结束。')
            return
        now = time.monotonic()
        if now >= self.next_preferences:
            self._update_output()
        if self.paused:
            return
        if now - self.last_advance > 20:
            self.error('音频加载或播放超时，请检查歌曲和输出设备。')
            return
        player = self.engine.player
        if not self.seek_sent:
            if (player.mediaStatus() in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferingMedia, QMediaPlayer.BufferedMedia)
                    and (self.offset <= 0 or player.isSeekable())):
                self.seek_sent = True
                if self.offset > 0:
                    player.setPosition(round(self.offset * 1000))
                player.play()
            return
        if player.playbackState() != QMediaPlayer.PlayingState:
            return
        position = player.position()
        if position <= self.offset * 1000 or position == self.last_position:
            return
        self.last_position = position
        self.last_advance = now
        self.elapsed = max(0., position / 1000 - self.offset)
        if not self.loaded:
            self.loaded = True
            self.started.emit()
        if self.live:
            self.progress.emit(self.elapsed if self.duration is None else min(self.duration, self.elapsed))
            if self.live and self.duration is not None and self.elapsed >= self.duration:
                self.done()

    def clock(self):
        # The helper reports every 100 ms. Interpolate between real samples for
        # smooth note travel, but only confirmed audio progress can finish a clip.
        if not self.loaded or self.paused:
            return self.elapsed
        interpolated = self.elapsed + min(.12, time.monotonic() - self.last_advance)
        return interpolated if self.duration is None else min(self.duration, interpolated)

    def toggle_pause(self):
        if self.live and self.loaded:
            self.paused = not self.paused
            self.last_advance = time.monotonic()
            if self.paused:
                self.engine.player.pause()
            else:
                self.engine.player.play()

    def done(self):
        self.stop()
        self.finished.emit()

    def error(self, message):
        if self.live:
            self.stop()
            self.failed.emit(message)

    def stop(self):
        self.live = self.paused = self.loaded = False
        self.timer.stop()
        if self.engine is not None and not self.engine.player.source().isEmpty():
            self.engine.player.stop()
            self.engine.player.setSource(QUrl())
        if self.token:
            self.mod.services.audio_release(self.token)
            self.token = None
        if getattr(self.mod, 'activity_audio_owner', None) is self:
            self.mod.activity_audio_owner = None

    def _retire_engine(self):
        engine, self.engine = self.engine, None
        if engine is None:
            return
        engine.closing = True
        engine.pending.clear()
        engine.setParent(QCoreApplication.instance())
        process = engine.process
        if process.state() == process.ProcessState.NotRunning:
            engine.deleteLater()
            return
        process.finished.connect(engine.deleteLater)
        engine.write({'cmd':'close'})
        def finish_close():
            if process.state() == process.ProcessState.NotRunning:
                engine.deleteLater()
            else:
                process.kill()
        QTimer.singleShot(1500, engine, finish_close)

    def close(self):
        self.stop()
        self._retire_engine()
