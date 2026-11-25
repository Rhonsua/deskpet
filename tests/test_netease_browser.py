import json
from pathlib import Path
import tempfile
import unittest

from deskpet.music.players.netease_player_worker import official_page, login_cookie
from deskpet.music.netease.login_progress import WebScanProgress, qr_stage, record_login_progress


class BrowserBoundaryTests(unittest.TestCase):
    def test_last_progress_file_cannot_contain_account_or_exception_data(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'TianyiPet-NetEase-login.json'
            record_login_progress({'type': 'fatal', 'step': 'cookie', 'stage': 'scanned', 'at': 123,
                                   'error': 'secret', 'protected': 'secret'}, directory)
            data = json.loads(report.read_text())
            self.assertEqual(set(data), {'state', 'time', 'step', 'stage', 'at'})
            self.assertEqual(data['step'], 'cookie')
            record_login_progress({'type':'session', 'protected':'secret'}, directory)
            data = json.loads(report.read_text())
            self.assertEqual(set(data), {'time', 'state'})
            self.assertEqual(data['state'], 'session')
            self.assertEqual(list(Path(directory).iterdir()), [report])

    def test_only_official_https_top_level(self):
        self.assertTrue(official_page('https://music.163.com/#/my/'))
        for url in ('http://music.163.com/', 'https://music.163.com.evil.test/',
                    'https://evil.test/?music.163.com', 'https://user@music.163.com/',
                    'https://music.163.com:444/', 'file:///tmp/page', 'javascript:alert(1)', None):
            self.assertFalse(official_page(url), url)

    def test_only_known_cookies_from_owned_official_profile(self):
        cookies = [('MUSIC_U', 'fake', '.music.163.com', '/'),
                   ('__csrf', 'fake-csrf', '.163.com', '/'),
                   ('MUSIC_U', 'parent-domain', '.163.com', '/'),
                   ('NMTID', '"invalid optional value"', '.music.163.com', '/'),
                   ('unrelated', 'ignore', '.163.com', '/'),
                   ('MUSIC_U', 'evil', '.evil.test', '/'),
                   ('MUSIC_U', 'wrong-path', '.music.163.com', '/other')]
        self.assertEqual(login_cookie(cookies), 'MUSIC_U=fake; __csrf=fake-csrf')
        self.assertEqual(login_cookie(reversed(cookies)), 'MUSIC_U=fake; __csrf=fake-csrf')


class WebScanProgressTests(unittest.TestCase):
    def test_poll_codes_accept_official_top_level_and_wrapped_responses(self):
        for code, stage in ((800, 'expired'), (801, 'waiting'), (802, 'scanned'), (803, 'confirmed')):
            self.assertEqual(qr_stage({'code': code}), stage)
            self.assertEqual(qr_stage({'code': 200, 'data': {'code': code}}), stage)
        self.assertEqual(qr_stage({'code': 8821, 'data': {'code': 803}}), 'site_rejected')
        for invalid in (None, [], {}, {'code': '803'}, {'code': 200}, {'data': []}, {'code': True}):
            self.assertIsNone(qr_stage(invalid))

    def test_scan_alone_keeps_the_same_code_until_phone_confirmation(self):
        scan = WebScanProgress()
        self.assertEqual(scan.without_session(10, manual=True), ('waiting_checked', False))
        scan.observe('scanned', 12)
        self.assertEqual(scan.without_session(13), ('scanned', False))
        scan.observe('waiting', 15)
        self.assertEqual(scan.without_session(37), ('scan_unconfirmed', False))
        self.assertEqual(scan.without_session(38, manual=True), ('scan_unconfirmed', False))
        scan.observe('new_code', 40)
        self.assertEqual(scan.without_session(40), ('waiting', False))

    def test_wait_hint_starts_from_the_current_code_and_never_reloads_it(self):
        scan = WebScanProgress()
        self.assertEqual(scan.without_session(1000), ('waiting', False))
        scan.observe('new_code', 1000)
        scan.observe('waiting', 1030)
        self.assertEqual(scan.without_session(1045), ('waiting_checked', False))
        scan.observe('new_code', 1050)
        self.assertEqual(scan.without_session(1051), ('waiting', False))

    def test_static_qr_is_distinct_from_an_official_waiting_response(self):
        scan = WebScanProgress()
        scan.site_result('new_code', 100)
        self.assertEqual(scan.without_session(101, qr_visible=True), ('waiting', False))
        self.assertEqual(scan.without_session(127, qr_visible=True), ('poll_stalled', False))
        scan.site_result('waiting', 128)
        self.assertEqual(scan.without_session(129, qr_visible=True), ('waiting', False))
        scan.site_result('scanned', 130)
        self.assertEqual(scan.without_session(131, qr_visible=True), ('scanned', False))

    def test_after_confirmation_refreshes_only_once_then_waits_on_the_official_site(self):
        scan = WebScanProgress()
        scan.observe('confirmed', 2)
        for stale in ('waiting', 'expired', 'scanned', 'confirmed'):
            scan.observe(stale, 8)
        self.assertEqual(scan.without_session(9), ('confirmed', False))
        self.assertEqual(scan.without_session(10), ('refresh_after_confirm', True))
        self.assertEqual(scan.without_session(12, manual=True), ('refresh_after_confirm', False))
        self.assertEqual(scan.without_session(18), ('confirmed_no_session', False))
        scan.observe('new_code', 20)
        scan.observe('waiting', 21)
        self.assertEqual(scan.without_session(21), ('replacement_qr', False))
        scan.observe('scanned', 22)
        scan.observe('confirmed', 23)
        self.assertEqual(scan.without_session(24, manual=True), ('refresh_after_confirm', True))

    def test_visible_qr_wins_over_background_checks_until_confirmation(self):
        scan = WebScanProgress()
        scan.observe('waiting', 1)
        self.assertEqual(scan.without_session(2, verification='credential', qr_visible=True), ('waiting', False))
        scan.observe('scanned', 3)
        self.assertEqual(scan.without_session(4, verification='verification_session', qr_visible=True), ('scanned', False))
        scan.observe('confirmed', 5)
        self.assertEqual(scan.without_session(6, verification='credential', qr_visible=True), ('credential', False))
        self.assertEqual(scan.without_session(13, verification='verification_session', qr_visible=True), ('refresh_after_confirm', True))
        self.assertEqual(scan.without_session(30, verification='credential', qr_visible=True), ('confirmed_no_session', False))

    def test_challenge_remains_open_during_phone_handoff(self):
        scan = WebScanProgress()
        scan.observe('confirmed', 2)
        self.assertEqual(scan.without_session(15, verification='verification_rejected'), ('verification_rejected', False))
        self.assertIsNone(scan.refreshed)


if __name__ == '__main__':
    unittest.main()
