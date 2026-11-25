"""Owned, temporary WebView2 login; no access to Edge/Bilibili profiles."""
import base64
import json
import weakref

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from deskpet.runtime.workers import worker_command
from .login_progress import STATUS, failure_message
from .storage import protect, session_data

PREFIX = b'TIANYI_NETEASE_LOGIN '


class BrowserLogin(QObject):
    completed = Signal(object)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._epoch = 0
        self.process = self._new_process()
        self.active = False
        self.buffer = b''
        self.worker_args = []

    def _new_process(self):
        process = QProcess(self)
        epoch = self._epoch
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        owner_ref, process_ref = weakref.ref(self), weakref.ref(process)
        def dispatch(method, *args):
            owner, child = owner_ref(), process_ref()
            if owner is not None and child is not None:
                getattr(owner, method)(*args, process=child, epoch=epoch)
        process.readyReadStandardOutput.connect(lambda: dispatch('_read'))
        process.readyReadStandardError.connect(lambda: dispatch('_stderr'))
        process.errorOccurred.connect(lambda error: dispatch('_error', error))
        process.finished.connect(lambda *_: dispatch('_finished'))
        return process

    def _stderr(self, process=None, epoch=None):
        if process is self.process and epoch == self._epoch:
            process.readAllStandardError()

    def _dispose_process(self, process):
        for signal in (process.readyReadStandardOutput, process.readyReadStandardError,
                       process.errorOccurred, process.finished):
            signal.disconnect()
        if process.state() == QProcess.ProcessState.NotRunning:
            process.deleteLater()
            return
        # Deleting a running QProcess waits for it. Keep the abandoned helper
        # alive outside the page until it exits, without holding up the GUI.
        process.setParent(QCoreApplication.instance())
        process.finished.connect(process.deleteLater)
        QTimer.singleShot(800, process, lambda: process.kill()
                          if process.state() != QProcess.ProcessState.NotRunning else None)

    def start(self):
        self.cancel()
        self._dispose_process(self.process)
        self.process = self._new_process()
        self.buffer = b''
        self.process.readAllStandardOutput()
        self.process.readAllStandardError()
        self.active = True
        env = QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONIOENCODING', 'utf-8')
        env.insert('PYTHONUNBUFFERED', '1')
        self.process.setProcessEnvironment(env)
        program, arguments = worker_command('netease')
        self.process.start(program, arguments + self.worker_args)

    def _read(self, process=None, epoch=None):
        if process is not None and (process is not self.process or epoch != self._epoch):
            return
        chunk = bytes(self.process.readAllStandardOutput())
        if not self.active:
            return
        self.buffer += chunk
        if len(self.buffer) > 256000:
            self._fail('登录窗口返回数据过大，已停止。')
            return
        while b'\n' in self.buffer and self.active:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(PREFIX):
                continue
            try:
                event = json.loads(line[len(PREFIX):])
                kind = event['type']
                if kind == 'session':
                    # Even the private pipe carries an encrypted credential envelope.
                    encoded = event['protected']
                    if not isinstance(encoded, str) or len(encoded) > 100000:
                        raise ValueError('invalid envelope')
                    raw = protect(base64.b64decode(encoded, validate=True), decrypt=True)
                    session = session_data(json.loads(raw), '')
                    self.active = False
                    self.buffer = b''
                    self.completed.emit(session)
                    return
                elif kind == 'ready':
                    self.status.emit(STATUS['opening'])
                elif kind == 'status' and event.get('stage') in STATUS:
                    self.status.emit(STATUS[event['stage']])
                elif kind == 'fatal':
                    self._fail(failure_message(event))
                elif kind == 'timeout':
                    self._fail('网页登录等待超过10分钟，已关闭；可重新打开。')
            except (ValueError, KeyError, TypeError, OSError):
                self._fail('无法接收网页登录结果，请重新打开登录窗口。')

    def _fail(self, text):
        if self.active:
            self.cancel()
            self.failed.emit(text)

    def _error(self, error, process=None, epoch=None):
        if process is not None and (process is not self.process or epoch != self._epoch):
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._fail('未能启动网易云的独立登录窗口。')

    def request_check(self):
        if self.active and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(b'{"cmd":"check"}\n')

    def _finished(self, process=None, epoch=None):
        if process is not None and (process is not self.process or epoch != self._epoch):
            return
        self._read(process, epoch)
        if process is not None and (process is not self.process or epoch != self._epoch):
            return
        if self.active:
            self.active = False
            self.failed.emit('登录窗口已关闭，尚未接收到有效登录状态。')

    def cancel(self):
        self._epoch += 1
        self.active = False
        self.buffer = b''
        if self.process.state() != QProcess.ProcessState.NotRunning:
            previous = self.process
            previous.write(b'{"cmd":"close"}\n')
            self._dispose_process(previous)
            self.process = self._new_process()
