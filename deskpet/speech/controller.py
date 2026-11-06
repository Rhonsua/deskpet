"""Isolated, cancellable speech synthesis and playback coordinator."""
import json
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from .player import SpeechPlayer, valid_wav


def speech_for_pet(pet):
    """The desktop and the chat window share one worker for this pet."""
    controller = getattr(pet, '_speech_controller', None)
    if controller is None:
        from deskpet.paths import PROJECT_ROOT
        from .config import speech_paths, speech_volume
        panel = pet.panel
        controller = SpeechController(lambda: getattr(panel, '_audio_router', None),
                                      panel.data_dir / 'chat' / 'speech',
                                      pet if isinstance(pet, QObject) else None,
                                      preferred_getter=lambda: panel.settings.value('audio_output_id', ''))
        controller.player.set_volume(speech_volume(panel.settings) / 100.0)
        controller.configure(*speech_paths(panel.settings, PROJECT_ROOT, panel.data_dir))
        controller.set_enabled(panel.settings.value('speech/enabled', False, type=bool))
        pet._speech_controller = controller
    return controller


class SpeechController(QObject):
    status = Signal(str)

    def __init__(self, router, directory, parent=None, *, preferred_getter=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.status_text = '语音已关闭。'
        self.status.connect(self._remember_status)
        self.player = SpeechPlayer(router, self, preferred_getter=preferred_getter)
        self.player.finished.connect(self._playback_finished)
        self.player.failed.connect(self._playback_failed)
        self.player.ready.connect(self._audio_ready)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.ready = False
        self.terminating = False
        self.warming = False
        self.restart_warm = False
        self.prepare_generation = 0
        self.stderr_tail = b''
        self.active = None
        self.delivery = None
        self.waiting_audio = False
        self.queued = None
        self.buffer = b''
        self.config = None
        self.pack_stamp = None
        self.output = None
        self.retired = []
        self.closing = False
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.setSingleShot(True)
        self.cleanup_timer.timeout.connect(self._cleanup)

    def _remember_status(self, text):
        self.status_text = text

    def configure(self, python, engine, config):
        value = (str(python), str(engine), str(config))
        stamp = None
        if Path(config).suffix.lower() == '.zip':
            try:
                info = Path(config).stat()
                stamp = (info.st_size, info.st_mtime_ns)
            except OSError:
                pass
        if value != self.config or stamp != self.pack_stamp:
            self.stop()
            self.config = value
            self.pack_stamp = stamp
            if self.player.enabled and not self._configured():
                self.player.set_enabled(False)
                self.player.set_enabled(True)
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self._kill_worker()
            if self.player.enabled and not self.closing:
                if self._configured():
                    self.player.prepare()
                self._schedule_prepare()

    def set_enabled(self, enabled):
        self.player.set_enabled(enabled)
        if not enabled:
            self.stop()
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self._kill_worker()
            self.status.emit('语音已关闭。')
        elif not self.closing:
            if self._configured():
                self.player.prepare()
            if self.player.audio_failed:
                return
            if not self.ready or not self.player.is_ready:
                self.status.emit('正在准备天依的声音…')
            self._schedule_prepare()

    def _schedule_prepare(self):
        self.prepare_generation += 1
        generation = self.prepare_generation
        QTimer.singleShot(0, lambda: self.prepare() if generation == self.prepare_generation else None)

    def _configured(self):
        return bool(self.config and Path(self.config[0]).is_file()
                    and Path(self.config[1]).is_dir() and Path(self.config[2]).is_file())

    def prepare(self):
        """Load only the model, without generating or playing audio."""
        if self.closing or not self.player.enabled:
            return
        if not self._configured():
            self.status.emit('请先配置本机语音运行环境。')
            return
        if self.ready and not self.terminating:
            return
        if self.process.state() != QProcess.ProcessState.NotRunning and not self.terminating:
            return
        self.warming = True
        self.timer.start(180000)
        self.status.emit('正在准备语音，首次稍慢。')
        if self.terminating:
            self.restart_warm = True
        else:
            self._start()

    def speak(self, text, *, deliver=None):
        if not self.player.enabled or not text.strip() or self.closing:
            return False
        if self.player.audio_failed:
            self.status.emit('语音播放设备不可用，请重新启用朗读。')
            return False
        if deliver is not None and len(text) > 1000:
            self.status.emit('回复较长，已改为显示文字。')
            return False
        if not self._configured():
            self.status.emit('请先配置本机语音运行环境。')
            return False
        self.stop(preserve_warm=True)
        ticket = self.player.begin()
        self.output = self.directory / ('speech-' + uuid.uuid4().hex + '.wav')
        self.active = ticket
        self.delivery = deliver
        self.queued = dict(cmd='synthesize', id=ticket, text=text[:1000], output=str(self.output))
        self.timer.start(180000)
        if self.process.state() == QProcess.ProcessState.NotRunning and not self.terminating:
            self._start()
        elif self.ready and not self.terminating:
            self._send()
        if self.active == ticket:
            self.status.emit('正在准备语音，首次稍慢。' if self.warming else '正在准备语音…')
        return True

    def _start(self):
        if (not self.queued and not self.warming) or self.closing or self.terminating:
            return
        self.ready = False
        self.buffer = b''
        self.stderr_tail = b''
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('PYTHONUNBUFFERED', '1')
        env.insert('TORCH_FORCE_WEIGHTS_ONLY_LOAD', '1')
        env.insert('HF_HUB_OFFLINE', '1')
        env.insert('TRANSFORMERS_OFFLINE', '1')
        cache = self.directory / 'hf-cache'
        try:
            cache.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._fail_delivery()
            self.status.emit('语音缓存无法写入，请检查磁盘空间和文件夹权限。')
            return
        env.insert('HF_HOME', str(cache))
        env.remove('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD')
        self.process.setProcessEnvironment(env)
        self.process.setProgram(self.config[0])
        self.process.setArguments([str(Path(__file__).with_name('worker.py')), self.config[1], self.config[2]])
        self.process.start()

    def _send(self):
        command, self.queued = self.queued, None
        if command and not self.terminating:
            self.process.write((json.dumps(command, ensure_ascii=False) + '\n').encode('utf-8'))

    def _deliver(self):
        callback, self.delivery = self.delivery, None
        return callback is None or callback() is not False

    def _fail_delivery(self):
        callback, self.delivery = self.delivery, None
        self.stop()
        if callback is not None:
            callback()

    def stop(self, *, preserve_warm=False):
        if not preserve_warm:
            self.prepare_generation += 1
        self.delivery = None
        self.waiting_audio = False
        self.player.stop()
        waiting_for_warm = preserve_warm and self.warming and self.queued is not None
        if not (preserve_warm and self.warming and (self.active is None or waiting_for_warm)):
            self.timer.stop()
        self.queued = None
        if self.output:
            self.retired.append(self.output)
            self.output = None
        was_active, self.active = self.active, None
        cancel_warm = self.warming and not preserve_warm
        if not preserve_warm:
            self.warming = False
            self.restart_warm = False
        if ((was_active is not None and not waiting_for_warm) or cancel_warm) and self.process.state() != QProcess.ProcessState.NotRunning:
            self._kill_worker()
        elif self.process.state() == QProcess.ProcessState.NotRunning or self.ready:
            self._cleanup()

    def _kill_worker(self):
        # kill() is asynchronous: until finished, this process owns all pipe events.
        if not self.terminating:
            self.terminating = True
            self.ready = False
            self.buffer = b''
            self.process.kill()

    def _read_stderr(self):
        chunk = bytes(self.process.readAllStandardError())
        # Only retain initialization diagnostics, before any chat text is sent.
        if not self.ready and not self.terminating:
            self.stderr_tail = (self.stderr_tail + chunk)[-4096:]

    def _playback_failed(self, message):
        if self.active is not None:
            self._fail_delivery()
        self.status.emit('语音播放失败：' + (str(message)[:300] or '请检查音频输出设备。'))

    def _playback_finished(self):
        if self.output and self.active is None:
            self.retired.append(self.output)
            self.output = None
            if self.ready and self.player.is_ready:
                self.status.emit('语音已就绪。')
        self._cleanup()

    def _cleanup(self):
        remaining = []
        for path in self.retired:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                remaining.append(path)
        self.retired = remaining
        if remaining and not self.closing:
            self.cleanup_timer.start(500)

    def _read(self):
        chunk = bytes(self.process.readAllStandardOutput())
        if self.terminating:
            return
        self.buffer += chunk
        if len(self.buffer) > 1024 * 1024:
            self.status.emit('语音后台输出异常，已停止。')
            self._fail_delivery()
            return
        while b'\n' in self.buffer and not self.terminating:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'TIANYI_SPEECH '):
                continue
            try:
                event = json.loads(line[len(b'TIANYI_SPEECH '):])
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get('type')
            if kind == 'ready':
                self.ready = True
                self.warming = False
                self.restart_warm = False
                self.stderr_tail = b''
                if self.active is None:
                    self.timer.stop()
                if self.player.is_ready:
                    self.status.emit('语音已就绪。')
                self._send()
            elif kind == 'fatal':
                self._read_stderr()
                detail = self.stderr_tail.decode('utf-8', errors='replace').strip()[-500:]
                self.status.emit('语音初始化失败：' + str(event.get('message', '未知错误'))[:300]
                                 + (' 初始化信息：' + detail if detail else ''))
                self._fail_delivery()
            elif self.active is not None and event.get('id') == self.active:
                if kind == 'completed':
                    output = self.output
                    if event.get('path') != str(output) or not valid_wav(output):
                        self._fail_delivery()
                        self.status.emit('语音文件无效，未播放。')
                        continue
                    self.waiting_audio = True
                    if self.player.is_ready:
                        self._audio_ready()
                    else:
                        self.timer.start(30000)
                elif kind == 'failed':
                    self._fail_delivery()
                    self.status.emit('语音合成失败：' + str(event.get('message', '未知错误'))[:300])

    def _audio_ready(self):
        if self.ready and self.active is None:
            self.status.emit('语音已就绪。')
        if not self.waiting_audio or self.active is None:
            return
        ticket, output = self.active, self.output
        self.waiting_audio = False
        self.timer.stop()
        deliver = self._deliver()
        if self.active != ticket or self.output != output:
            return
        self.active = None
        if deliver and self.player.play(ticket, output):
            self.status.emit('正在播放语音。')
        else:
            self._playback_finished()

    def _timeout(self):
        self._fail_delivery()
        self.status.emit('语音合成超时，已停止。')

    def _finished(self, *_):
        was_terminating = self.terminating
        had_active = self.active is not None
        had_warming = self.warming
        self.process.readAllStandardOutput()
        self._read_stderr()
        self.ready = False
        self.terminating = False
        self.buffer = b''
        self._cleanup()
        if was_terminating and (self.queued or self.restart_warm) and not self.closing:
            self.restart_warm = False
            self._start()
        elif was_terminating:
            self.warming = False
        elif had_active or self.queued or had_warming:
            callback, self.delivery = self.delivery, None
            self.active = self.queued = None
            self._playback_finished()
            self.warming = self.restart_warm = False
            self.timer.stop()
            detail = self.stderr_tail.decode('utf-8', errors='replace').strip()[-500:]
            self.status.emit('语音后台已退出。' + (' 初始化信息：' + detail if detail else ''))
            if callback is not None:
                callback()
        elif not self.closing and self.player.enabled:
            self.status.emit('语音后台已退出，点击试听可重新启动。')

    def _error(self, error):
        if self.terminating and error == QProcess.ProcessError.FailedToStart:
            QTimer.singleShot(0, self._finished)
        elif error == QProcess.ProcessError.FailedToStart:
            callback, self.delivery = self.delivery, None
            self.active = self.queued = None
            self._playback_finished()
            self.warming = self.restart_warm = False
            self.timer.stop()
            self.status.emit('无法启动语音后台，请检查 Python 路径。')
            if callback is not None:
                callback()

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._kill_worker()
            self.process.waitForFinished(2000)
        self.player.close()
        self._cleanup()
