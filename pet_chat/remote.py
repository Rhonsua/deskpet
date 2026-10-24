"""Nonblocking chat facade; first-use network initialization runs elsewhere."""
import json
from dataclasses import asdict
from PySide6.QtCore import QObject, QCoreApplication, QProcess, QProcessEnvironment, QTimer, Signal
from worker_command import worker_command


class ChatClient(QObject):
    partial = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    loadingChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.process.finished.connect(self._exited)
        self.process.errorOccurred.connect(self._process_error)
        self.ready = False
        self.closed = False
        self.generation = 0
        self.active = None
        self.pending = None
        self.buffer = b''
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def start(self, config, messages, test=False):
        config.validate()
        if self.closed:
            raise ValueError('聊天已关闭，请重新打开桌宠。')
        self.cancel()
        self.generation += 1
        self.active = self.generation
        self.pending = dict(cmd='start', id=self.active, config=asdict(config),
                            messages=messages, test=test)
        self.timer.start(90000)
        if self.ready:
            self._send_pending()
        elif self.process.state() == QProcess.ProcessState.NotRunning:
            self.buffer = b''
            self.loadingChanged.emit(True)
            env = QProcessEnvironment.systemEnvironment()
            env.insert('PYTHONIOENCODING', 'utf-8')
            env.insert('PYTHONUNBUFFERED', '1')
            self.process.setProcessEnvironment(env)
            program, args = worker_command('chat')
            self.process.setProgram(program)
            self.process.setArguments(args)
            self.process.start()
        else:
            self.loadingChanged.emit(True)

    def _write(self, value):
        # Credentials travel only over the private pipe, never argv or files.
        self.process.write((json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))

    def _send_pending(self):
        pending, self.pending = self.pending, None
        if pending is not None:
            self._write(pending)

    def cancel(self):
        active, self.active = self.active, None
        self.pending = None
        self.timer.stop()
        if active is not None and self.ready:
            self._write(dict(cmd='cancel', id=active))
        self.loadingChanged.emit(False)

    def _timeout(self):
        if self.active is not None:
            self.cancel()
            self.failed.emit('请求超过 90 秒，请稍后重试或更换模型。')

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > 2 * 1024 * 1024:
            self._broken('聊天后台响应过大，已停止接收。')
            self.process.kill()
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'TIANYI_CHAT '):
                continue
            try:
                event = json.loads(line[len(b'TIANYI_CHAT '):])
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get('type') == 'ready':
                self.ready = True
                self.loadingChanged.emit(False)
                self._send_pending()
                continue
            if self.active is None or event.get('id') != self.active:
                continue
            text = event.get('text')
            if not isinstance(text, str) or len(text) > 16000:
                continue
            kind = event.get('type')
            if kind == 'partial':
                self.partial.emit(text)
            elif kind in ('completed', 'failed'):
                self.active = None
                self.timer.stop()
                (self.completed if kind == 'completed' else self.failed).emit(text)

    def _broken(self, message):
        had_request = self.active is not None
        self.ready = False
        self.active = self.pending = None
        self.buffer = b''
        self.timer.stop()
        self.loadingChanged.emit(False)
        if had_request and not self.closed:
            self.failed.emit(message)

    def _exited(self, *_):
        self._broken('聊天后台已退出，请重新发送；未完成的回复不会保存。')

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._broken('无法启动聊天后台，请检查程序文件是否完整。')

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.cancel()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            # Only final shutdown joins; send/cancel never wait on the helper.
            self.process.waitForFinished(1000)
