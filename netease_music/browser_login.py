"""Owned, temporary WebView2 login; no access to Edge/Bilibili profiles."""
import base64
import json
import weakref

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from worker_command import worker_command
from .storage import protect, session_data

PREFIX = b'TIANYI_NETEASE_LOGIN '
STATUS = {
    'waiting':'等待网页扫码；目前尚未观察到官网的扫码确认提示。',
    'scanned':'官网已显示扫描成功，请在手机上确认登录。',
    'confirmed':'官网已接到手机确认，正在等待网页写入登录会话；此时尚未接回账号。',
    'site_rejected':'官网扫码请求被拒绝或需要验证，请在网页登录窗口完成验证或刷新二维码后重试。',
    'expired':'官网显示二维码已失效，请在网页登录窗口刷新二维码。',
    'checking':'正在重新检测官方网页登录状态。',
    'credential':'检测到登录凭据，正在验证账号并接回桌宠。',
    'verification_retry':'检测到凭据，但官网尚未返回可验证的账号；会继续检测，也可点击重新检测。',
    'verification_native':'网页尚未接回账号，正在通过桌宠直接核验当前登录凭据。',
    'verification_session':'已取得凭据，但网易云尚未确认有效账号；请检查网页是否已显示头像，或改用直接扫码。',
    'verification_rejected':'账号核验请求被网易云拒绝；请在官网完成验证，或改用直接扫码。',
    'verification_network':'账号核验连接失败，将自动重试；也可点击重新检测。',
    'verification_response':'账号核验未返回可识别的结果，将自动重试；也可改用直接扫码。',
}


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
        process.deleteLater()

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
                    self.status.emit('请在网易云官方网页点击登录，完成扫码或验证后将自动返回歌单。')
                elif kind == 'status' and event.get('stage') in STATUS:
                    self.status.emit(STATUS[event['stage']])
                elif kind == 'fatal':
                    self._fail('网易云登录窗口未能完成初始化或读取登录状态，请关闭后重试；需要 Edge WebView2。')
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
            self._fail('无法启动网易云登录窗口，请检查浏览器组件是否完整。')

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
            self.process.write(b'{"cmd":"close"}\n')
            if not self.process.waitForFinished(800):
                self.process.kill()
                self.process.waitForFinished(500)
