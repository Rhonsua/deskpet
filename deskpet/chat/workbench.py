"""Own the bundled official Harness web workbench, confined to loopback."""
import os
import re
from pathlib import Path
from deskpet.paths import PROJECT_ROOT
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

ROOT = PROJECT_ROOT
HOME = ROOT / 'local-work' / 'harness-workbench'

class Workbench(QObject):
    status = Signal(str)
    ready = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.running = False
        self.url = ''
        self._buffer = ''
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._startup_timeout)

    def start(self, workspace):
        if self.running:
            if self.url:
                self.ready.emit(self.url)
            return
        folder = Path(workspace).resolve(strict=True)
        if not folder.is_dir():
            raise ValueError('请选择工作文件夹')
        cli = ROOT / '.harness-venv' / 'Scripts' / 'dsh.exe'
        if not cli.exists():
            raise ValueError('工作环境尚未安装，请运行 packaging/setup_harness.ps1。')
        HOME.mkdir(parents=True, exist_ok=True)
        patch = HOME / 'privacy.patch.yml'
        patch.write_text('''- id: session-log-deepseek
  config:
    enabled: false
- id: session-telemetry-otel
  disabled: true
- id: sandbox-policy
  config:
    mode: workspace-write
- id: approval
  config:
    policy: ask
- id: permission
  config:
    defaultPreset: workspace-write
''', encoding='utf-8')
        env = QProcessEnvironment.systemEnvironment()
        env.insert('DSH_HOME', str(HOME))
        env.insert('DSH_TELEMETRY_DISABLED', '1')
        env.insert('DSH_PERMISSION_MODE', 'workspace-write')
        # Workbench credentials are managed by its own official settings UI.
        for name in ('DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL'):
            env.remove(name)
        process = QProcess(self)
        self.process = process
        process.setProcessEnvironment(env)
        process.setProgram(str(cli))
        process.setArguments(['--profile','web','--patch',str(patch),'--host','127.0.0.1','--port','0','--no-open'])
        process.setWorkingDirectory(str(folder))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.finished.connect(lambda *args: self._finished(process))
        process.errorOccurred.connect(lambda error: self._error(process, error))
        self.running = True
        self.url = ''
        self._buffer = ''
        self.status.emit('正在启动官方工作台…')
        self._timer.start(30000)
        process.start()

    def _read(self, process):
        if process is not self.process:
            return
        text = bytes(process.readAllStandardOutput()).decode('utf-8', 'replace')
        self._buffer = (self._buffer + text)[-16000:]
        if not self.url:
            match = re.search(r'http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_-]+', self._buffer)
            if match:
                self._timer.stop()
                self.url = match.group(0)
                self.status.emit('官方工作台已就绪')
                self.ready.emit(self.url)

    def _error(self, process, error):
        if process is self.process and error == QProcess.FailedToStart:
            self.status.emit('官方工作台无法启动，请检查独立环境。')
            self._finished(process)

    def _startup_timeout(self):
        if self.running and not self.url:
            self.status.emit('官方工作台启动超过 30 秒，已停止。')
            self.stop()

    def _kill_tree(self, process, wait=False):
        if process.state() == QProcess.NotRunning:
            return
        if os.name == 'nt' and process.processId():
            killer = QProcess(self)
            killer.setProgram('taskkill.exe')
            killer.setArguments(['/PID', str(process.processId()), '/T', '/F'])
            killer.start()
            if wait:
                killer.waitForFinished(5000)
                if killer.state() != QProcess.NotRunning:
                    killer.kill()
                    killer.waitForFinished(500)
                killer.deleteLater()
            else:
                killer.finished.connect(killer.deleteLater)
        else:
            process.kill()
        if wait:
            process.waitForFinished(2000)

    def stop(self):
        self._timer.stop()
        if self.process and self.running:
            self.status.emit('正在关闭官方工作台…')
            self._kill_tree(self.process)

    def shutdown(self):
        """Bounded cleanup that does not depend on the application event loop."""
        self._timer.stop()
        process = self.process
        if process:
            self._kill_tree(process, wait=True)
            self._finished(process)

    def _finished(self, process):
        if process is not self.process:
            return
        self._timer.stop()
        self.process = None
        self.running = False
        self.url = ''
        self._buffer = ''
        self.status.emit('官方工作台已停止')
        self.stopped.emit()
        process.deleteLater()
