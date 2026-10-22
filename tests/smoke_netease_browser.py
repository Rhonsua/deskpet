"""Real WebView2 HttpOnly-cookie / DPAPI / Qt handoff, synthetic account only."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
from netease_music.browser_login import BrowserLogin


def main():
    app = QApplication([])
    login = BrowserLogin()
    login.worker_args = ['--self-test']
    sessions, errors = [], []
    login.completed.connect(sessions.append)
    login.failed.connect(errors.append)
    try:
        login.start()
        until = time.monotonic() + 40
        while not sessions and not errors and time.monotonic() < until:
            app.processEvents()
            time.sleep(.02)
        assert not errors, errors
        assert len(sessions) == 1, 'browser session handoff timed out'
        assert sessions[0]['uid'] == '77' and sessions[0]['api'] == ''
        assert sessions[0]['cookie'] == 'MUSIC_U=synthetic-only'
        until = time.monotonic() + 8
        while login.process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < until:
            app.processEvents()
            time.sleep(.02)
        assert login.process.state() == QProcess.ProcessState.NotRunning
        assert not login.active and not login.buffer
        # Close-before-result must not deliver a session from an abandoned worker.
        login.start()
        login.cancel()
        app.processEvents()
        assert len(sessions) == 1 and not login.active
        print('PASS: isolated WebView2, HttpOnly cookie, encrypted handoff, automatic close, cancellation')
    finally:
        login.cancel()


if __name__ == '__main__':
    main()
