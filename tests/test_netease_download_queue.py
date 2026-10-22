"""Download preparation must use download permission, never playback fallback."""
from types import SimpleNamespace
import unittest

from netease_music.download_queue import NeteaseDownloads
from netease_music.service import ApiError, SessionExpired


ITEM = dict(id='123', title='合成曲目', artists='人工测试')


class FakeService:
    def __init__(self, media=None, song=None, media_error=None, song_error=None):
        self.calls = []
        self.media_result = media or dict(id='123', unavailable=False, trial=False,
                                         url='https://m1.music.126.net/synthetic.mp3')
        self.song_result = song or dict(id='123', lrc='[00:00]人工短句', lrc_status='逐句可用')
        self.media_error, self.song_error = media_error, song_error

    def media(self, item_id, download=False):
        self.calls.append(('media', item_id, download))
        if self.media_error: raise self.media_error
        if False: yield None
        return self.media_result

    def song(self, item_id):
        self.calls.append(('song', item_id))
        if self.song_error: raise self.song_error
        if False: yield None
        return self.song_result


def prepare(service, lyrics_only=False):
    operation = NeteaseDownloads._prepare(service, dict(ITEM), lyrics_only)
    try:
        next(operation)
    except StopIteration as done:
        return done.value
    raise AssertionError('fake service should never perform IO')


class DownloadPreparationTests(unittest.TestCase):
    def test_download_permission_then_lyrics(self):
        service = FakeService()
        result = prepare(service)
        self.assertEqual(service.calls, [('media', '123', True), ('song', '123')])
        self.assertEqual(result['lrc'], '[00:00]人工短句')
        self.assertEqual(result['item'], ITEM)

    def test_trial_unavailable_and_missing_url_never_fall_back(self):
        for media in (dict(unavailable=True, trial=False, url=''),
                      dict(unavailable=False, trial=True, url='https://m1.music.126.net/trial.mp3'),
                      dict(unavailable=False, trial=False, url='')):
            with self.subTest(media=media):
                service = FakeService(media=media)
                result = prepare(service)
                self.assertEqual(service.calls, [('media', '123', True)])
                self.assertEqual(result['lrc'], '')
                self.assertEqual(result['media'], media)

    def test_permission_error_is_not_downgraded_to_playback_endpoint(self):
        service = FakeService(media_error=ApiError('没有下载权限'))
        with self.assertRaises(ApiError): prepare(service)
        self.assertEqual(service.calls, [('media', '123', True)])

    def test_only_lrc_never_requests_audio(self):
        service = FakeService(media_error=AssertionError('lyrics-only requested media'))
        result = prepare(service, lyrics_only=True)
        self.assertEqual(service.calls, [('song', '123')])
        self.assertIsNone(result['media'])
        self.assertEqual(result['lrc'], '[00:00]人工短句')

    def test_lyric_failure_keeps_authorized_media_explicitly(self):
        service = FakeService(song_error=ApiError('合成歌词错误'))
        result = prepare(service)
        self.assertTrue(result['media']['url'])
        self.assertEqual(result['lrc'], '')
        self.assertIn('歌词获取失败', result['lyric_status'])

    def test_expiry_is_not_treated_as_missing_lyrics(self):
        for lyrics_only in (False, True):
            service = FakeService(song_error=SessionExpired('测试过期'))
            with self.subTest(lyrics_only=lyrics_only), self.assertRaises(SessionExpired):
                prepare(service, lyrics_only)
        service = FakeService(media_error=SessionExpired('测试过期'))
        with self.assertRaises(SessionExpired): prepare(service)


if __name__ == '__main__':
    unittest.main()
