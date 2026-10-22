"""Synthetic WebView2 tests for both official-page profile acquisition routes."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
from netease_music.browser_login import BrowserLogin


def main():
    app = QApplication.instance() or QApplication([])
    login = BrowserLogin()
    sessions, errors, statuses = [], [], []
    login.completed.connect(sessions.append)
    login.failed.connect(errors.append)
    login.status.connect(statuses.append)
    try:
        for fetch in (False, True):
            login.worker_args = ['--self-test'] + (['--fixture-fetch'] if fetch else [])
            expected = len(sessions) + 1
            login.start()
            deadline = time.monotonic() + 35
            while len(sessions) < expected and not errors and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            assert not errors, errors
            assert len(sessions) == expected, 'synthetic browser flow timed out'
            assert sessions[-1]['uid'] == '77'
            assert sessions[-1]['cookie'] == 'MUSIC_U=synthetic-only'
            deadline = time.monotonic() + 6
            while login.process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            assert login.process.state() == QProcess.ProcessState.NotRunning
        assert any('手机上确认' in text for text in statuses), 'visible same-origin iframe scan state was missed'
        assert any('检测到登录凭据' in text for text in statuses), 'credential verification state was missed'
        print('PASS: native JS without promise bridge, visible iframe scan state, real weapi AES-CBC fetch verified by native decryptor, encrypted handoff')
    finally:
        login.cancel()


if __name__ == '__main__':
    main()
