"""List pagination, account reuse and queue preservation; no live account required."""
import base64
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, QProcess
from PySide6.QtWidgets import QApplication, QWidget
from deskpet.music.players.bilibili_import import BilibiliImport, ImportCancelled, Source, parse_source
from deskpet.music.players.bilibili_account import AccountBridge, cookie_header, decode_cookie, native_cookie
from deskpet.music.players.bilibili_import_dialog import BilibiliImportDialog, ImportService
from deskpet.music.players.bilibili_player import BilibiliPlayer


def video(n, **extra):
    return dict(bvid=f'BV{n:010d}', title=f'歌曲 {n}', **extra)


class ImportTests(unittest.TestCase):
    def test_browser_and_share_links(self):
        cases = [
            ('https://space.bilibili.com/123/lists/456?type=season', 'season', '456', '123'),
            ('https://space.bilibili.com/123/lists/456?type=series', 'series', '456', '123'),
            ('https://space.bilibili.com/123/channel/collectiondetail?sid=456', 'season', '456', '123'),
            ('https://space.bilibili.com/123/favlist?fid=456&ftype=create', 'favorite', '456', '123'),
            ('https://www.bilibili.com/list/ml456?oid=123', 'favorite', '456', ''),
            ('https://www.bilibili.com/medialist/detail/ml456', 'favorite', '456', ''),
            ('https://www.bilibili.com/list/123?sid=456&bvid=BV0000000001', 'series', '456', '123'),
            ('https://www.bilibili.com/medialist/play/123?business=space_collection&business_id=456', 'season', '456', '123'),
            ('https://space.bilibili.com/123/', 'space', '', '123'),
            ('123', 'space', '', '123'),
            ('https://space.bilibili.com/123/upload/video', 'uploads', '', '123'),
            ('分享给你 https://b23.tv/Ab123。', 'short', '', ''),
        ]
        for url, kind, identifier, mid in cases:
            with self.subTest(url=url):
                source = parse_source(url)
                self.assertEqual((source.kind, source.id, source.mid), (kind, identifier, mid))
        self.assertEqual(parse_source('BV0000000001').url, 'https://www.bilibili.com/video/BV0000000001/')

    def test_untrusted_or_ambiguous_links(self):
        for value in ('https://www.bilibili.com.evil.test/list/ml1', 'https://user@www.bilibili.com/list/ml1',
                      'http://127.0.0.1/list/ml1', 'https://space.bilibili.com:456/123',
                      'https://space.bilibili.com/123/lists/456?type=series&type=season',
                      'https://space.bilibili.com/123/favlist?fid=-2', 'https://b23.tv/a https://b23.tv/b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_source(value)
        client = BilibiliImport()
        client.raw = Mock(return_value='http://localhost/private')
        with self.assertRaises(ValueError):
            client.resolve('https://b23.tv/abc')

    def test_favorites_pagination_dedup_and_invalid(self):
        client = BilibiliImport()
        client.api = Mock(side_effect=[dict(info=dict(title='我的歌单'), medias=[video(1), video(2)], has_more=True),
            dict(medias=[video(2), dict(bvid='bad', title='失效'), video(3, type=12), video(4)], has_more=False)])
        result = client.read('https://www.bilibili.com/list/ml123')
        self.assertEqual([t['title'] for t in result['tracks']], ['歌曲 1', '歌曲 2', '歌曲 4'])
        self.assertEqual(result['title'], '我的歌单')
        self.assertEqual(result['skipped'], 2)
        self.assertEqual([call.kwargs['pn'] for call in client.api.call_args_list], [1, 2])

    def test_season_complete_and_multipart_keep_part_numbers(self):
        client = BilibiliImport()
        client.api = Mock(side_effect=[dict(archives=[video(n) for n in range(1, 31)], page=dict(total=31)),
                                       dict(archives=[video(31)], page=dict(total=31))])
        self.assertEqual(len(client.read(Source('season', '20', '10'))['tracks']), 31)
        client.api = Mock(return_value=dict(**video(1), pages=[dict(page=1, part='第一首'), dict(page=3, part='第三首')]))
        result = client.read('https://www.bilibili.com/video/BV0000000001/')
        self.assertTrue(result['tracks'][1]['url'].endswith('?p=3'))
        self.assertIn('第三首', result['tracks'][1]['title'])

    def test_failed_or_repeated_pages_never_return_partial_success(self):
        client = BilibiliImport()
        client.api = Mock(side_effect=[dict(medias=[video(1)], has_more=True), ValueError('暂时不可用')])
        with self.assertRaisesRegex(ValueError, '不可用'):
            client.read(Source('favorite', '1'))
        client.api = Mock(return_value=dict(medias=[video(1)], has_more=True))
        with self.assertRaisesRegex(ValueError, '重复'):
            client.read(Source('favorite', '1'))
        self.assertEqual(client.api.call_count, 2)

    def test_cancellation_and_item_bound(self):
        client = BilibiliImport()
        client.stopped.set()
        client.api = Mock()
        with self.assertRaises(ImportCancelled):
            client.read(Source('favorite', '1'))
        client.api.assert_not_called()
        client = BilibiliImport()
        client.api = Mock(return_value=dict(medias=[video(1), video(2)], has_more=False))
        with patch('deskpet.music.players.bilibili_import.MAX_ITEMS', 1), self.assertRaisesRegex(ValueError, '超过'):
            client.read(Source('favorite', '1'))

    def test_catalogue_nested_page_and_favorites(self):
        client = BilibiliImport()
        def api(path, **params):
            if 'seasons_series' in path:
                page = params['page_num']
                return dict(items_lists=dict(page=dict(total=21), seasons_list=[dict(meta=dict(season_id=page, name=f'合集{page}', total=2))]))
            return dict(list=[dict(id=3, title='收藏音乐', media_count=4)])
        client.api = Mock(side_effect=api)
        result = client.read(Source('space', mid='123'))
        self.assertEqual(len(result['choices']), 4)
        self.assertEqual(client.api.call_count, 3)

    def test_my_account_only_requests_its_own_folders(self):
        client = BilibiliImport(cookie='SESSDATA=synthetic')
        def api(path, **params):
            if path.endswith('/nav'):
                return dict(isLogin=True, mid=123, uname='测试用户')
            self.assertEqual(params['up_mid'], '123')
            return dict(list=[dict(id=4, title='我的音乐', media_count=2)], has_more=False)
        client.api = Mock(side_effect=api)
        result = client.read(Source('mine'))
        self.assertEqual(result['account'], '测试用户')
        self.assertEqual(len(result['choices']), 1)

    def test_anonymous_wbi_and_private_list_errors(self):
        client = BilibiliImport()
        client.raw = Mock(return_value=json.dumps(dict(code=-101, data=dict(isLogin=False, wbi_img={}))).encode())
        self.assertFalse(client.api('/x/web-interface/nav')['isLogin'])
        with self.assertRaisesRegex(ValueError, '登录'):
            client.account()
        client.raw = Mock(return_value=json.dumps(dict(code=-403)).encode())
        with self.assertRaisesRegex(ValueError, '登录'):
            client.read(Source('favorite', '1'))

    def test_followed_folders_use_count_pagination_and_collection_owner(self):
        client = BilibiliImport()
        client.api = Mock(side_effect=[dict(list=[]),
            dict(count=21, list=[dict(id=7, type=21, title='收藏的合集', upper=dict(mid=999))]),
            dict(count=21, list=[dict(id=8, type=11, title='收藏的歌单', mid=888)])])
        choices = client.catalogue('123', only_favorites=True)['choices']
        self.assertEqual(choices[0]['source'], Source('season', '7', '999'))
        self.assertEqual(choices[1]['source'], Source('favorite', '8', '888'))
        self.assertEqual(client.api.call_args.kwargs['pn'], 2)


class AccountTests(unittest.TestCase):
    def test_nonempty_native_cookies_read_on_browser_thread(self):
        on_ui = False
        class Func:
            def __class_getitem__(cls, _):
                return lambda fn: fn
        def invoke(fn):
            nonlocal on_ui
            on_ui = True
            try:
                return fn()
            finally:
                on_ui = False
        def field(value):
            self.assertTrue(on_ui, 'Cookie COM property accessed off the browser thread')
            return value
        class Cookie:
            Name = property(lambda _: field('SESSDATA'))
            Value = property(lambda _: field('synthetic'))
            Domain = property(lambda _: field('.bilibili.com'))
        task = Mock()
        task.GetAwaiter.return_value.GetResult.return_value = [Cookie()]
        window = Mock()
        window.native.Invoke.side_effect = invoke
        window.native.webview.CoreWebView2.CookieManager.GetCookiesAsync.return_value = task
        with patch.dict('sys.modules', System=SimpleNamespace(Func=Func, Object=object)):
            self.assertEqual(native_cookie(window), 'SESSDATA=synthetic')

    def test_cookie_scope_and_encrypted_roundtrip(self):
        header = cookie_header([('SESSDATA','synthetic-only','.bilibili.com'), ('private','no','.bilibili.com'),
                                ('bili_jct','no','evil.test'), ('bili_ticket','bad\nvalue','.bilibili.com')])
        self.assertEqual(header, 'SESSDATA=synthetic-only')
        from deskpet.music.netease.storage import protect
        encrypted = base64.b64encode(protect(header.encode())).decode()
        self.assertNotIn('synthetic-only', encrypted)
        self.assertEqual(decode_cookie(encrypted), header)

    def test_reuses_browser_without_navigating_or_pausing(self):
        window, webview, emit = Mock(), Mock(), Mock()
        bridge = AccountBridge(window, webview, emit)
        with patch('deskpet.music.players.bilibili_account.native_cookie', return_value='SESSDATA=synthetic'):
            bridge.request('one')
        event = emit.call_args.args[0]
        self.assertEqual(event['request'], 'one')
        self.assertIn('protected', event)
        window.load_url.assert_not_called()
        window.evaluate_js.assert_not_called()
        webview.create_window.assert_not_called()


class ImportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_path = str(Path(self.temp.name) / 'settings.ini')
        self.owner = QWidget()
        self.owner.settings = QSettings(self.settings_path, QSettings.Format.IniFormat)
        self.owner.set_alternating = Mock()
        self.player = BilibiliPlayer(self.owner)
        self.player.watchdog.stop()
        self.dialog = BilibiliImportDialog(self.player)
        self.player.import_dialog = self.dialog
        self.dialog.service.start = Mock()
        self.player.request_import_account = Mock()
        self.player.cancel_import_account = Mock()

    def tearDown(self):
        self.dialog.shutdown()
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_my_favorites_reuses_web_account_and_ignores_stale_result(self):
        self.dialog.read_mine()
        request = self.dialog.account_request
        self.player.request_import_account.assert_called_once_with(request, login=False)
        with patch('deskpet.music.players.bilibili_import_dialog.decode_cookie', return_value='SESSDATA=synthetic'):
            self.player.accountReady.emit(dict(request=request, protected='opaque'))
        self.dialog.service.start.assert_called_once_with(Source('mine'), 'SESSDATA=synthetic')
        self.dialog.service.start.reset_mock()
        self.dialog.read_mine()
        request = self.dialog.account_request
        self.dialog.cancel_read()
        self.player.accountReady.emit(dict(request=request, protected='opaque'))
        self.dialog.service.start.assert_not_called()

    def test_signed_out_opens_official_login_and_recheck(self):
        self.dialog.read_mine()
        self.player.accountReady.emit(dict(request=self.dialog.account_request, login_required=True))
        self.assertTrue(self.player.request_import_account.call_args.kwargs['login'])
        self.assertTrue(self.dialog.mine_button.isEnabled())
        self.dialog.read_mine()
        self.assertFalse(self.player.request_import_account.call_args.kwargs['login'])

    def test_public_import_survives_webview_failure(self):
        self.dialog.start_read('https://www.bilibili.com/list/ml123')
        self.player.accountReady.emit(dict(request=self.dialog.account_request, error='unavailable'))
        self.dialog.service.start.assert_called_once_with('https://www.bilibili.com/list/ml123')

    def test_queue_preserved_deduplicated_and_saved(self):
        urls = [f'https://www.bilibili.com/video/BV{n:010d}/' for n in (1, 2)]
        self.player.tracks = [dict(url=urls[0], title='')]
        self.player.current_url = urls[0]
        self.player.active = self.player.playing = True
        self.player.queue.reset(urls[:1], 0)
        self.player.render()
        self.player.list.setCurrentRow(0)
        with patch.object(self.player, 'send') as send:
            self.dialog.loaded(dict(title='测试歌单', tracks=[dict(url=u, title=f'第{i}首') for i,u in enumerate(urls)], skipped=0), '')
        send.assert_not_called()
        self.assertTrue(self.player.playing)
        self.assertEqual(self.player.current_url, urls[0])
        self.assertEqual(self.player.queue.paths, urls)
        self.assertEqual(self.player.queue.index, 0)
        self.assertEqual(len(self.player.tracks), 2)
        self.assertIn('跳过 1', self.dialog.status.text())
        self.dialog.loaded(None, '读取失败')
        saved = QSettings(self.settings_path, QSettings.Format.IniFormat)
        self.assertEqual(len(json.loads(saved.value('bilibili_tracks'))), 2)
        self.assertEqual(self.player.tracks[0]['title'], '第0首')

    def test_catalogue_selection_passes_target(self):
        source = Source('season', '45', '12')
        self.dialog.loaded(dict(choices=[dict(source=source, title='天依音乐合集', count=20)], warning=''), '')
        self.dialog.lists.setCurrentRow(0)
        self.assertTrue(self.dialog.add_button.isEnabled())
        self.dialog.add_selected()
        self.assertEqual(self.dialog.pending_source, source)

    def test_cancelled_job_results_cannot_modify_playlist(self):
        service = ImportService()
        results = []
        service.ready.connect(lambda *args: results.append(args))
        service.active = True
        ticket = service.ticket
        service.cancel()
        service.finish(ticket, dict(tracks=[video(1)]), '')
        self.assertEqual(results, [])


if __name__ == '__main__':
    unittest.main()
