"""Offline WebView2 checks from the login button through account and playlist handoff."""
import os
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication
from deskpet.music.netease.browser_login import BrowserLogin
from deskpet.music.netease.login_progress import STATUS


def official_handoff_from_widget(app):
    from deskpet.music.netease.widget import NeteaseWidget
    with tempfile.TemporaryDirectory() as directory:
        widget = NeteaseWidget(directory)
        errors, stages, requests = [], [], []
        def controller(parent):
            login = BrowserLogin(parent)
            login.worker_args = ['--self-test', '--fixture-official-session']
            login.failed.connect(errors.append)
            login.status.connect(stages.append)
            return login
        def load_collections(kind, operation):
            operation.close()
            requests.append(kind)
            assert kind == 'collections'
            result = dict(created=[dict(id='456', title='合成测试歌单')], collected=[], warnings=[], complete=True)
            QTimer.singleShot(0, lambda: widget._completed(kind, result))
        widget.show()
        widget.remember.setChecked(False)
        try:
            with patch('deskpet.music.netease.browser_login.BrowserLogin', side_effect=controller), \
                 patch.object(widget.client, 'run', side_effect=load_collections):
                widget.account_buttons['扫码登录网易云'].click()
                deadline = time.monotonic() + 32
                while not widget.collections.topLevelItemCount() and not errors and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.02)
                assert not errors and requests == ['collections'], (errors, stages, requests)
                assert widget.session['uid'] == '77' and not widget._browser_pending
                assert widget.collections.topLevelItem(0).text(1) == '合成测试歌单'
                assert STATUS['waiting'] in stages and STATUS['confirmed'] in stages, stages
                deadline = time.monotonic() + 5
                while widget.browser_login.process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.02)
                assert widget.browser_login.process.state() == QProcess.ProcessState.NotRunning
        finally:
            widget.shutdown()
            widget.close()


def main():
    app = QApplication.instance() or QApplication([])
    official_handoff_from_widget(app)
    print('PASS: regular login button to official browser account and playlist display', flush=True)
    login = BrowserLogin()
    sessions, errors, statuses = [], [], []
    login.completed.connect(sessions.append)
    login.failed.connect(errors.append)
    login.status.connect(statuses.append)
    try:
        for fixture in ([], ['--fixture-delayed-session'], ['--fixture-unverified-session'],
                        ['--fixture-rendered-account'], ['--fixture-rotated-session']):
            start = len(statuses)
            login.worker_args = ['--self-test', *fixture]
            expected = len(sessions) + 1
            login.start()
            deadline = time.monotonic() + 35
            while len(sessions) < expected and not errors and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            assert not errors, errors
            assert len(sessions) == expected, (fixture, statuses[start:], 'synthetic browser flow timed out')
            assert sessions[-1]['uid'] == '77'
            suffix = 'rotated' if '--fixture-rotated-session' in fixture else 'only'
            assert sessions[-1]['cookie'] == 'MUSIC_U=synthetic-' + suffix
            if '--fixture-delayed-session' in fixture or '--fixture-unverified-session' in fixture:
                stages = statuses[start:]
                assert stages.count(STATUS['refresh_after_confirm']) == 1, stages
                assert stages.index(STATUS['confirmed']) < stages.index(STATUS['refresh_after_confirm']), stages
                if '--fixture-delayed-session' in fixture:
                    assert STATUS['credential'] in stages[stages.index(STATUS['refresh_after_confirm']) + 1:], stages
            deadline = time.monotonic() + 6
            while login.process.state() != QProcess.ProcessState.NotRunning and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.02)
            assert login.process.state() == QProcess.ProcessState.NotRunning
        assert any('手机上确认' in text for text in statuses), 'visible same-origin iframe scan state was missed'
        assert any('检测到登录凭据' in text for text in statuses), 'credential verification state was missed'
        print('PASS: delayed/rotated cookies, stale rendered identity rejected, confirmed page reload, verified owner and encrypted handoff')
    finally:
        login.cancel()


if __name__ == '__main__':
    main()
