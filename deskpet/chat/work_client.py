"""Qt process transport for the optional, isolated Harness environment."""
import json
import os
import sys
import uuid
from pathlib import Path
from deskpet.paths import PROJECT_ROOT
from urllib.parse import urlsplit, urlunsplit
from .harness_runtime import runtime_directory
from PySide6.QtCore import QObject, QProcess, QTimer, Signal, QStandardPaths

ROOT = PROJECT_ROOT
PYTHON = ROOT / '.harness-venv' / 'Scripts' / 'python.exe'


def session_root():
    # Installed files are replaceable. Never keep sessions under the program
    # directory or under an official DSH application's installation directory.
    if getattr(sys, 'frozen', False):
        return Path(QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'work-sessions'
    return ROOT / 'local-work' / 'harness'


def harness_worker_command():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).with_name('TianyiWorker.exe'), ['--harness-worker']
    return PYTHON, ['-u', '-m', 'deskpet.chat.harness_worker']

def harness_endpoint(url):
    parts = urlsplit(url)
    if parts.hostname == 'api.deepseek.com':
        return 'https://api.deepseek.com/anthropic'
    if parts.hostname in ('localhost', '127.0.0.1', '::1'):
        path = parts.path.removesuffix('/chat/completions').rstrip('/')
        return urlunsplit((parts.scheme, parts.netloc, path, '', ''))
    raise ValueError('工作模式需要 DeepSeek 官方 Messages 服务；当前自定义聊天接口不能直接用于工作模式。')

class WorkClient(QObject):
    event = Signal(dict)
    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    approval = Signal(dict)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.busy = False
        self.buffer = b''
        self.terminal = False
        self.session_id = None
        self._pending_session_id = None
        self._secret = ''
        self._cancelled = False

    def start(self, config, prompt, workspace, session_id=None, auto_approve=False):
        if self.busy:
            raise ValueError('已有工作正在运行')
        url = config.validate()
        folder = Path(workspace).resolve(strict=True)
        if not folder.is_dir():
            raise ValueError('请选择工作目录')
        program, arguments = harness_worker_command()
        if not program.is_file():
            self.failed.emit('工作进程缺失，请重新安装桌宠。' if getattr(sys, 'frozen', False)
                             else '工作环境尚未安装，请运行 packaging/setup_harness.ps1。')
            return
        url = harness_endpoint(url)
        if session_id is not None and (not isinstance(session_id, str) or not session_id.isalnum() or len(session_id) > 64):
            raise ValueError('工作会话编号无效')
        candidate = session_id or uuid.uuid4().hex
        home = session_root() / candidate
        if session_id is not None and not (home / 'session-ready').is_file():
            raise ValueError('此会话的后端记录不可用；已保留页面历史，请取消“继续上一工作会话”后新建会话。')
        self._secret = config.api_key
        self._pending_session_id = candidate
        self._cancelled = False
        self.buffer = b''
        self.terminal = False
        self.busy = True
        self.busy_changed.emit(True)
        process = QProcess(self)
        self.process = process
        process.setProgram(str(program))
        process.setArguments(arguments)
        process.setWorkingDirectory(str(ROOT))
        payload = dict(prompt=prompt, workspace=str(folder), model=config.model,
                       api_key=config.api_key, base_url=url,
                       home=str(home), session_id=candidate, auto_approve=auto_approve is True,
                       resume=session_id is not None and (home / 'session-ready').exists())
        payload['runtime_dir'] = str(runtime_directory(session_root().parent)
                                    if getattr(sys, 'frozen', False) else runtime_directory())
        process.started.connect(lambda: self._send(payload) if process is self.process else None)
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(lambda *args: self._finished(process))
        process.errorOccurred.connect(lambda _: self._error(process))
        process.start()

    def can_resume(self):
        sid = self.session_id
        return (isinstance(sid, str) and sid.isalnum() and len(sid) <= 64
                and (session_root() / sid / 'session-ready').is_file())

    def _send(self, payload):
        if self.process:
            self.process.write((json.dumps(payload, ensure_ascii=False)+'\n').encode('utf-8'))

    def approve(self, request_id, approved):
        self._send(dict(type='approval', id=request_id, approved=approved is True))

    def cancel(self):
        if self.process:
            self._cancelled = True
            self._send(dict(type='cancel'))
            process = self.process
            QTimer.singleShot(2500, lambda: self._kill_tree(process))

    def _kill_tree(self, process, wait=False):
        if process is not self.process or process.state() == QProcess.NotRunning:
            return
        if os.name == 'nt' and process.processId() > 0:
            killer = QProcess(self)
            killer.setProgram('taskkill.exe')
            killer.setArguments(['/PID', str(process.processId()), '/T', '/F'])
            killer.start()
            if wait:
                if not killer.waitForFinished(5000):
                    killer.kill()
                    killer.waitForFinished(500)
                    process.kill()
                killer.deleteLater()
            else:
                killer.finished.connect(killer.deleteLater)
        else:
            process.kill()
        if wait:
            process.waitForFinished(2000)

    def shutdown(self):
        process = self.process
        if process:
            self._kill_tree(process, wait=True)
            self._finished(process)

    def _read(self, process):
        if process is not self.process:
            return
        self.buffer += bytes(process.readAllStandardOutput())
        if len(self.buffer) > 2 * 1024 * 1024:
            self.cancel()
            self.terminal = True
            self.buffer = b''
            self.failed.emit('工作状态数据过大，已停止。')
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    continue
                kind = event.get('type')
                if kind == 'event':
                    if isinstance(event.get('event'), dict):
                        body = event['event']
                        if body.get('type') == 'session_ready':
                            if body.get('session_id') != self._pending_session_id or self._pending_session_id is None:
                                continue
                            self.session_id = self._pending_session_id
                        self.event.emit(event['event'])
                elif kind == 'approval':
                    if isinstance(event.get('request'), dict) and isinstance(event['request'].get('id'), (str, int)):
                        self.approval.emit(event['request'])
                elif kind == 'progress':
                    if isinstance(event.get('text'), str):
                        if event.get('phase') == 'setup':
                            self.event.emit({'type': 'runtime_setup', 'text': event['text']})
                        else:
                            self.progress.emit(event['text'])
                elif kind in ('completed', 'failed'):
                    if not isinstance(event.get('text'), str):
                        continue
                    if self.terminal:
                        continue
                    self.terminal = True
                    if self._cancelled:
                        self.failed.emit('工作已停止。')
                    elif isinstance(event.get('text'), str):
                        getattr(self, kind).emit(event['text'])
            except (ValueError, KeyError):
                continue

    def _error(self, process):
        if process is not self.process:
            return
        if not self.terminal:
            self.terminal = True
            self.failed.emit('无法启动 Harness 独立工作进程。')
        if self.process and self.process.state() == QProcess.NotRunning:
            self._finished(process)

    def _finished(self, process):
        if process is not self.process or not self.busy:
            return
        self._read(process)  # Drain the final readiness/result lines before disposal.
        if not self.terminal:
            self.failed.emit('工作已停止。')
        self.busy = False
        self.busy_changed.emit(False)
        self._secret = ''
        self._pending_session_id = None
        if self.process:
            self.process.deleteLater()
            self.process = None
