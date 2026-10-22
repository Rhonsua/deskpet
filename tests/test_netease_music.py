"""Synthetic NetEase protocol fixtures only; no account or full real lyrics."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from netease_music.links import api_base, canonical_link, music_id, parse_link
from netease_music.service import ApiError, Request, Service, SessionExpired, lrc_info
from netease_music.storage import Cache


def song(item_id):
    return dict(id=int(item_id), name='测试曲目' + str(item_id), ar=[dict(name='测试歌手')], dt=1000)


def drive(operation, handler):
    try:
        request = next(operation)
        while True:
            assert isinstance(request, Request)
            try:
                value = handler(request)
            except ApiError as error:
                request = operation.throw(error)
            else:
                request = operation.send(value)
    except StopIteration as done:
        return done.value


SESSION = dict(api='https://api.example.test', uid='77', nickname='测试用户', cookie='MUSIC_U=not-a-real-cookie')


class NeteaseLinkTests(unittest.TestCase):
    def test_links_and_ids(self):
        for value in ['https://music.163.com/song?id=185633', 'https://music.163.com/#/song?id=185633',
                      'http://music.163.com/m/song?id=185633&userid=77', 'https://y.music.163.com/m/song?id=185633']:
            self.assertEqual(parse_link(value), ('song', '185633'))
        self.assertEqual(parse_link('https://music.163.com/playlist?id=123'), ('playlist', '123'))
        self.assertEqual(canonical_link('song', '123'), 'https://music.163.com/song?id=123')
        for value in ['https://music.163.com.evil.test/song?id=1', 'https://user:key@music.163.com/song?id=1',
                      'https://music.163.com/song?id=1&id=2', 'https://music.163.com/song?id=-1',
                      'https://music.163.com/song?id=0', 'https://music.163.com/song?id=1#evil',
                      'https://music.163.com/artist?id=1', 'https://163cn.tv/abc', '1',
                      'https://music.163.com:999/song?id=1', 'file:///song?id=1',
                      'https://music.163.com/song?id=1&redirect=https://evil.test']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_link(value)
        for value in [True, 0, '-1', '1.0', '１２', '1' * 20]:
            with self.assertRaises(ValueError):
                music_id(value)

    def test_api_trust_boundary(self):
        self.assertEqual(api_base('https://api.example.test/netease/'), 'https://api.example.test/netease')
        self.assertEqual(api_base('http://[::1]:3000'), 'http://[::1]:3000')
        for value in ['http://public.example', 'https://u:p@example.test', 'https://example.test?a=1',
                      'https://example.test/#x', 'https://example.test:bad', 'file:///a']:
            with self.assertRaises(ValueError):
                api_base(value)


class NeteaseServiceTests(unittest.TestCase):
    def test_metadata_and_lrc_and_instrumental(self):
        service = Service()
        requests = []
        def respond(request):
            requests.append(request)
            return dict(songs=[song(1)]) if '/detail' in request.url else dict(lrc=dict(lyric='[00:01.00]测试'))
        result = drive(service.song('1'), respond)
        self.assertEqual(result['id'], '1')
        self.assertEqual(result['lrc'], '[00:01.00]测试')
        self.assertTrue(all(not req.cookie and not req.community for req in requests))
        self.assertEqual(lrc_info(dict(nolyric=True))[0], '')
        self.assertEqual(lrc_info(dict(lrc=dict(lyric='无时间轴')))[0], '')
        with self.assertRaises(ApiError):
            lrc_info(dict(lrc=dict(lyric=[])))

    def test_lyric_failure_keeps_metadata_but_auth_failure_propagates(self):
        def respond(request):
            if '/detail' in request.url:
                return dict(songs=[song(1)])
            raise ApiError('temporary')
        result = drive(Service().song('1'), respond)
        self.assertIn('失败', result['lrc_status'])
        self.assertEqual(result['lrc'], '')
        def expired(request):
            if '/detail' in request.url:
                return dict(songs=[song(1)])
            raise SessionExpired('expired')
        with self.assertRaises(SessionExpired):
            drive(Service(SESSION['api'], SESSION).song('1'), expired)

    def test_full_ordered_playlist_batches_deduplicate_and_partial_pages(self):
        offsets = []
        def respond(request):
            if request.url.endswith('/playlist/detail'):
                return dict(playlist=dict(name='大歌单', trackCount=405,
                    trackIds=[dict(id=i) for i in range(1, 406)] + [dict(id=1)], tracks=[]))
            ids = request.params['ids'].split(',')
            offsets.append(len(ids))
            return dict(songs=[song(i) for i in reversed(ids)])
        result = drive(Service(SESSION['api']).playlist('99'), respond)
        self.assertEqual(offsets, [200, 200, 5])
        self.assertEqual([item['id'] for item in result['tracks']], [str(i) for i in range(1, 406)])
        self.assertTrue(result['complete'])
        def partial(request):
            if request.url.endswith('/song/detail') and request.params['ids'].startswith('201,'):
                raise ApiError('page unavailable')
            return respond(request)
        result = drive(Service(SESSION['api']).playlist('99'), partial)
        self.assertFalse(result['complete'])
        self.assertEqual(result['count'], 205)
        self.assertEqual(len(result['missing']), 200)
        self.assertTrue(result['warnings'])

    def test_missing_track_ids_uses_full_track_pagination(self):
        offsets = []
        def respond(request):
            if request.url.endswith('/playlist/detail'):
                return dict(playlist=dict(name='分页歌单', trackCount=401, tracks=[]))
            offset = request.params['offset']
            offsets.append(offset)
            return dict(songs=[song(i) for i in range(offset + 1, min(offset + 201, 402))])
        result = drive(Service(SESSION['api']).playlist('9'), respond)
        self.assertEqual(offsets, [0, 200, 400])
        self.assertEqual(result['count'], 401)
        self.assertTrue(result['complete'])

    def test_public_missing_ids_is_explicit_partial_and_no_fake_paging(self):
        def respond(request):
            return dict(result=dict(name='受限公开歌单', trackCount=500, tracks=[song(1), song(2)]))
        result = drive(Service().playlist('9'), respond)
        self.assertFalse(result['complete'])
        self.assertEqual(result['count'], 2)

    def test_account_playlist_pagination_and_unordered_likes(self):
        offsets = []
        def respond(request):
            self.assertEqual(request.cookie, SESSION['cookie'])
            if request.url.endswith('/user/playlist'):
                offset = request.params['offset']
                offsets.append(offset)
                return dict(more=offset == 0, playlist=[dict(id=offset + 1, name='歌单', creator=dict(userId=77 if offset == 0 else 88))])
            if request.url.endswith('/likelist'):
                return dict(ids=[5, 2, 5, 9])
            return dict(songs=[song(9), song(2), song(5)])
        service = Service(SESSION['api'], SESSION)
        collections = drive(service.collections(), respond)
        self.assertEqual(offsets, [0, 100])
        self.assertEqual(len(collections['created']), 1)
        self.assertEqual(len(collections['collected']), 1)
        result = drive(service.likes(), respond)
        self.assertEqual([item['id'] for item in result['tracks']], ['5', '2', '9'])
        self.assertIn('不代表客户端排序', result['warnings'][0])

    def test_likes_prefers_official_playlist_order(self):
        paths = []
        def respond(request):
            paths.append(request.url)
            if request.url.endswith('/user/playlist'):
                return dict(more=False, playlist=[dict(id=123, name='喜欢', specialType=5, creator=dict(userId=77))])
            return dict(playlist=dict(name='喜欢', trackCount=2, tracks=[song(9), song(2)]))
        result = drive(Service(SESSION['api'], SESSION).likes(), respond)
        self.assertEqual([item['id'] for item in result['tracks']], ['9', '2'])
        self.assertFalse(any(path.endswith('/likelist') for path in paths))

    def test_invalid_collection_items_mark_partial_even_on_last_page(self):
        def respond(request):
            return dict(more=False, playlist=[dict(id=1, name='正常', creator=dict(userId=77)),
                         dict(id='bad', name='异常'), dict(id=2, name=4, creator=dict(userId=77)),
                         dict(id=3, name='无创建者')])
        result = drive(Service(SESSION['api'], SESSION).collections(), respond)
        self.assertEqual(len(result['created']), 1)
        self.assertFalse(result['complete'])
        self.assertTrue(result['warnings'])

    def test_qr_cookie_not_sent_until_confirmed_and_community_remains_compatible(self):
        direct = next(Service().qr())
        self.assertTrue(direct.direct)
        self.assertFalse(direct.cookie)
        self.assertEqual(direct.url, 'https://music.163.com/api/login/qrcode/unikey')
        def qr_response(request):
            self.assertFalse(request.cookie)
            return dict(data=dict(unikey='fake-key')) if request.url.endswith('/key') else dict(data=dict(qrimg='data:image/png;base64,fake'))
        qr = drive(Service(SESSION['api']).qr(), qr_response)
        self.assertEqual(qr['key'], 'fake-key')
        def confirm(request):
            if request.url.endswith('/check'):
                self.assertFalse(request.cookie)
                return dict(code=803, cookie=SESSION['cookie'])
            self.assertEqual(request.cookie, SESSION['cookie'])
            return dict(data=dict(profile=dict(userId=77, nickname='测试用户')))
        result = drive(Service(SESSION['api']).check_qr('fake-key'), confirm)
        self.assertEqual(result['session'], SESSION)
        self.assertNotIn(SESSION['cookie'], repr(Service(SESSION['api'], SESSION).request('/user/playlist')))


class NeteaseStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Cache(Path(self.temp.name) / 'netease')

    def test_snapshots_are_separate_and_complete_cache_survives_partial_refresh(self):
        full = dict(title='完整', complete=True, tracks=[], count=2, total=2)
        self.cache.save_snapshot('playlist', '1', full)
        self.assertFalse(self.cache.save_snapshot('playlist', '1', dict(full, complete=False, count=1)))
        self.assertEqual(self.cache.snapshot('playlist', '1')['data'], full)
        self.cache.save_snapshot('song', '2', dict(lrc='[00:01]测试', lrc_status='可用'))
        self.assertFalse(self.cache.save_snapshot('song', '2', dict(lrc='', lrc_status='获取失败')))
        self.assertEqual(self.cache.snapshot('song', '2')['data']['lrc'], '[00:01]测试')
        self.assertFalse((Path(self.temp.name) / 'music.db').exists())

    def test_logout_clears_credentials_and_personal_not_public_snapshots(self):
        self.cache.save_snapshot('playlist', '1', dict(complete=True), True)
        self.cache.save_snapshot('playlist', '2', dict(complete=True), False)
        self.cache.write('session.json', dict(fake='encrypted-test'))
        self.cache.clear_private()
        self.assertFalse(self.cache.path('session.json').exists())
        self.assertFalse(self.cache.path('private').exists())
        self.assertIsNotNone(self.cache.snapshot('playlist', '2'))

    def test_credential_encryption_failure_preserves_prior_file(self):
        self.cache.write('session.json', dict(old='encrypted'))
        before = self.cache.path('session.json').read_bytes()
        with patch('netease_music.storage.protect', side_effect=ValueError('test')):
            with self.assertRaises(ValueError):
                self.cache.save_session(SESSION)
        self.assertEqual(self.cache.path('session.json').read_bytes(), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_dpapi_roundtrip_not_plaintext_and_api_origin_bound(self):
        self.cache.save_session(SESSION)
        text = self.cache.path('session.json').read_text()
        self.assertNotIn(SESSION['cookie'], text)
        self.assertNotIn(SESSION['nickname'], text)
        self.assertEqual(self.cache.load_session(SESSION['api']), (SESSION, ''))
        self.assertIsNone(self.cache.load_session('https://other.example')[0])


if __name__ == '__main__':
    unittest.main()
