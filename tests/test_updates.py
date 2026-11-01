import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QWidget

from deskpet.runtime import updates
from deskpet.ui.updates import UpdateController, CHECK_INTERVAL


BODY = b'MZexample installer bytes'


def release_data(version='0.6.2'):
    name = f'TianyiPet-{version}-Setup.exe'
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': False,
            'body': '新增工位功能\n修复问题', 'assets': [{
                'name': name, 'state': 'uploaded', 'size': len(BODY),
                'digest': 'sha256:' + hashlib.sha256(BODY).hexdigest(),
                'browser_download_url': f'{updates.RELEASES_URL}/download/v{version}/{name}'}]}


class UpdateTests(unittest.TestCase):
    def test_stable_numeric_comparison_and_asset_selection(self):
        self.assertEqual(updates.parse_release(release_data('0.6.10'), '0.6.9').version, '0.6.10')
        self.assertIsNone(updates.parse_release(release_data('0.6.1'), '0.6.1'))
        self.assertIsNone(updates.parse_release(release_data('0.5.0'), '0.6.1'))
        data = release_data()
        for field in ('prerelease', 'draft'):
            data[field] = True
            self.assertIsNone(updates.parse_release(data, '0.6.1'))
            data[field] = False
        for bad in ('v0.6.2-beta.1', '../../bad', '0.6', '0.06.2', None):
            data['tag_name'] = bad
            with self.assertRaises(updates.UpdateError):
                updates.parse_release(data, '0.6.1')

    def test_reject_wrong_package_and_external_or_ambiguous_download(self):
        for change in ({'name': 'TianyiPet-0.6.2-portable.zip'},
                       {'browser_download_url': 'https://example.com/setup.exe'},
                       {'size': -1}, {'size': True}, {'digest': 'sha256:broken'}):
            data = release_data()
            data['assets'][0].update(change)
            with self.assertRaises(updates.UpdateError):
                updates.parse_release(data, '0.6.1')
        data = release_data()
        data['assets'].append(copy.deepcopy(data['assets'][0]))
        with self.assertRaises(updates.UpdateError):
            updates.parse_release(data, '0.6.1')
        for url in ('http://github.com/a', 'https://github.com.evil.example/a',
                    'https://token@github.com/a', 'file:///setup.exe', 'https://github.com:444/a'):
            self.assertFalse(updates.allowed_url(url))
            with self.assertRaises(updates.UpdateError):
                updates.GitHubRedirect().redirect_request(None, None, 302, '', {}, url)
        self.assertTrue(updates.allowed_url('https://release-assets.githubusercontent.com/a?signature=abc'))

    def test_check_reads_public_release_without_a_github_token(self):
        with patch.object(updates, 'open_url', return_value=io.BytesIO(json.dumps(release_data()).encode())) as opened:
            result = updates.fetch_latest(threading.Event(), '0.6.1')
        self.assertEqual(result.version, '0.6.2')
        opened.assert_called_once_with(updates.LATEST_URL, api=True)
        with patch.object(updates, 'build_opener') as opener:
            updates.open_url(updates.LATEST_URL, api=True)
            request = opener.return_value.open.call_args.args[0]
            self.assertIsNone(request.get_header('Authorization'))
        for code in (404, 403, 429, 500):
            with patch.object(updates, 'open_url', side_effect=HTTPError('', code, '', {}, None)):
                if code == 404:
                    self.assertIsNone(updates.fetch_latest(threading.Event()))
                else:
                    with self.assertRaises(updates.UpdateError):
                        updates.fetch_latest(threading.Event())

    def test_verified_download_checksum_file_fallback_and_cleanup(self):
        release = updates.parse_release(release_data(), '0.6.1')
        with tempfile.TemporaryDirectory() as tmp:
            progress = []
            with patch.object(updates, 'open_url', return_value=io.BytesIO(BODY)):
                path = updates.download_release(release, tmp, threading.Event(), lambda a, b: progress.append((a, b)))
            self.assertEqual(path.read_bytes(), BODY)
            self.assertEqual(progress[-1], (len(BODY), len(BODY)))
            for wrong in (BODY[:-1], BODY + b'bad', b'X' * len(BODY)):
                with patch.object(updates, 'open_url', return_value=io.BytesIO(wrong)):
                    with self.assertRaises(updates.UpdateError):
                        updates.download_release(release, tmp, threading.Event(), lambda *args: None)
                self.assertEqual(path.read_bytes(), BODY)  # A failed retry cannot replace the good copy.
                self.assertEqual(list(Path(tmp).rglob('*.part')), [])
            data = release_data()
            data['assets'][0]['digest'] = None
            checksum_asset = {'name': 'SHA256SUMS.txt', 'state': 'uploaded',
                              'browser_download_url': f'{updates.RELEASES_URL}/download/v0.6.2/SHA256SUMS.txt'}
            data['assets'].append(checksum_asset)
            fallback = updates.parse_release(data, '0.6.1')
            sums = f'{release.sha256}  {release.filename}\n'.encode()
            with patch.object(updates, 'open_url', side_effect=[io.BytesIO(sums), io.BytesIO(BODY)]):
                self.assertEqual(updates.download_release(fallback, tmp, threading.Event(), lambda *args: None).read_bytes(), BODY)
            data['assets'].pop()
            with patch.object(updates, 'open_url') as opened:
                with self.assertRaises(updates.UpdateError):
                    updates.download_release(updates.parse_release(data, '0.6.1'), tmp, threading.Event(), lambda *args: None)
                opened.assert_not_called()

    def test_cancel_discards_partial_and_does_not_return_executable(self):
        release = updates.parse_release(release_data(), '0.6.1')
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(updates, 'open_url', return_value=io.BytesIO(BODY)):
                with self.assertRaises(updates.Cancelled):
                    updates.download_release(release, tmp, cancel, lambda *args: cancel.set())
            self.assertEqual(list(Path(tmp).rglob('*.part')), [])
            self.assertEqual(list(Path(tmp).rglob('*.exe')), [])

    def test_checksum_ambiguity_and_oversized_response(self):
        release = updates.parse_release(release_data(), '0.6.1')
        row = f'{release.sha256}  {release.filename}\n'
        for data in ('', row.replace(release.filename, 'wrong.exe'), row * 2):
            with self.assertRaises(updates.UpdateError):
                updates.checksum_from_text(data, release.filename)
        with self.assertRaises(updates.UpdateError):
            updates.read_limited(io.BytesIO(b'X' * 101), 100, threading.Event())


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel = QWidget()
        self.panel.data_dir = Path(self.tmp.name)
        self.panel.settings = QSettings(str(Path(self.tmp.name) / 'test.ini'), QSettings.Format.IniFormat)
        self.panel.update_check = QPushButton(self.panel)
        self.panel.update_page = QPushButton(self.panel)
        self.panel.update_note = QLabel(self.panel)
        self.panel.update_toggle = QCheckBox(self.panel)
        self.panel.update_toggle.setChecked(True)
        self.controller = UpdateController(self.panel)

    def tearDown(self):
        self.controller.shutdown()
        if self.controller.dialog:
            self.controller.dialog.close()
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_automatic_opt_out_and_interval_but_manual_can_check(self):
        c = self.controller
        with patch.object(c, 'launch_job') as launch, patch('deskpet.ui.updates.time.time', return_value=100000):
            self.panel.update_toggle.setChecked(False)
            c.check()
            launch.assert_not_called()
            self.panel.update_toggle.setChecked(True)
            c.settings.setValue('updates/last_check', 100000 - CHECK_INTERVAL + 1)
            c.check()
            launch.assert_not_called()
            c.check(manual=True)
            launch.assert_called_once()
            c.job = 'check'
            c.check(manual=True)
            launch.assert_called_once()  # Double click cannot start a second request.

    def test_skipped_release_manual_override_and_quiet_network_failure(self):
        c = self.controller
        release = updates.parse_release(release_data(), '0.6.1')
        c.settings.setValue('updates/skipped_version', release.version)
        with patch.object(c, 'offer_release') as offer:
            c.job = 'check'
            c.finish('check', release, '')
            offer.assert_not_called()
            c.manual = True
            c.job = 'check'
            c.finish('check', release, '')
            offer.assert_called_once_with(release)
            offer.reset_mock()
            c.job = 'check'
            c.finish('check', None, '网络未连接')
            offer.assert_not_called()
            self.assertIn('网络未连接', self.panel.update_note.text())

    def test_download_finish_does_not_cancel_itself_or_launch_installer(self):
        c = self.controller
        release = updates.parse_release(release_data(), '0.6.1')
        ready = Path(self.tmp.name) / release.filename
        ready.write_bytes(BODY)
        with patch.object(c, 'launch_job', side_effect=lambda kind, fn: setattr(c, 'job', kind)), \
                patch.object(c, 'offer_install') as offer, patch('deskpet.ui.updates.os.startfile') as launch:
            c.download(release)
            c.finish('download', ready, '')
            self.assertFalse(c.cancel.is_set())
            self.assertEqual(c.ready, ready)
            offer.assert_called_once()
            launch.assert_not_called()
            self.assertIsNone(c.progress)

    def test_cancelled_download_never_offers_install_and_late_results_are_ignored(self):
        c = self.controller
        with patch.object(c, 'offer_install') as offer:
            c.job = 'download'
            c.cancel.set()
            c.finish('download', Path(self.tmp.name) / 'never.exe', '')
            offer.assert_not_called()
            self.assertIsNone(c.ready)
            c.job = 'download'
            c.shutdown()
            c.finish('download', Path(self.tmp.name) / 'never.exe', '')
            offer.assert_not_called()

    def test_install_requires_explicit_choice_and_launch_failure_keeps_app_open(self):
        c = self.controller
        c.installable = True
        c.ready = Path(self.tmp.name) / 'TianyiPet-0.6.2-Setup.exe'
        c.ready.write_bytes(BODY)
        with patch('deskpet.ui.updates.os.startfile') as launch, \
                patch('deskpet.ui.updates.QApplication') as application:
            c.offer_install()
            next(button for button in c.dialog.buttons() if button.text() == '稍后安装').click()
            launch.assert_not_called()
            application.instance.return_value.quit.assert_not_called()
            c.offer_install()
            launch.side_effect = OSError('not found')
            next(button for button in c.dialog.buttons() if button.text() == '退出并打开安装程序').click()
            application.instance.return_value.quit.assert_not_called()
            self.assertIn('无法打开安装程序', self.panel.update_note.text())
            launch.side_effect = None
            c.offer_install()
            next(button for button in c.dialog.buttons() if button.text() == '退出并打开安装程序').click()
            application.instance.return_value.quit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
