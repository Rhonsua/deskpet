"""Normal media metadata, trial handling and CDN boundaries; no audio IO."""
import unittest

from netease_music.media import media_info, validate_media_url
from netease_music.service import ApiError, Service, SessionExpired
from tests.test_netease_music import SESSION, drive, song


URL = 'http://m10.music.126.net/fake-expiry/fake-signature/song.mp3?test=fixture'


def response(**changes):
    item = dict(id=123, code=200, url=URL, type='mp3', time=200000, size=3200000, freeTrialInfo=None)
    item.update(changes)
    return dict(code=200, data=[item])


class NeteaseMediaTests(unittest.TestCase):
    def test_official_audio_cdn_is_https_normalized(self):
        self.assertEqual(validate_media_url(URL), URL.replace('http:', 'https:', 1))
        for host in ('m701.music.126.net', 'm801.music.126.net', 'm7.music.126.net'):
            self.assertEqual(validate_media_url(f'https://{host}/fake.flac'), f'https://{host}/fake.flac')
        for value in ('file:///c:/music.mp3', 'https://127.0.0.1/music.mp3', 'http://localhost/test.mp3',
                      'https://10.0.0.1/test.mp3', 'https://[::1]/test.mp3',
                      'https://m10.music.126.net.evil.test/fake.mp3', 'https://evil.test/fake.mp3',
                      'https://p1.music.126.net/cover.jpg', 'https://m10.music.126.net/script.py',
                      'https://user:key@m10.music.126.net/fake.mp3', 'https://m10.music.126.net:999/fake.mp3',
                      'https://m10.music.126.net/fake.mp3#other', 'https://m10.music.126.net/a/../fake.mp3',
                      'https://m10.music.126.net/%2e%2e/fake.mp3', 'https://m10.music.126.net/fake%00.mp3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_media_url(value)

    def test_normal_play_result_has_stable_fields_and_does_not_infer_trial_from_fee(self):
        raw = response(fee=1, payed=0, freeTrialPrivilege=dict(resConsumable=True, userConsumable=True))
        result = media_info(raw, '123')
        self.assertEqual(set(result), {'id', 'url', 'extension', 'trial', 'trial_start_ms', 'duration_ms', 'size', 'unavailable', 'reason'})
        self.assertFalse(result['trial'])
        self.assertFalse(result['unavailable'])
        self.assertEqual(result['duration_ms'], 200000)
        self.assertTrue(result['url'].startswith('https://m10.music.126.net/'))

    def test_trial_segment_start_and_duration_and_download_refusal(self):
        raw = response(freeTrialInfo=dict(start=60, end=90))
        result = media_info(raw, '123')
        self.assertTrue(result['trial'])
        self.assertEqual(result['trial_start_ms'], 60000)
        self.assertEqual(result['duration_ms'], 30000)
        self.assertFalse(result['unavailable'])
        download = media_info(raw, '123', download=True)
        self.assertTrue(download['unavailable'])
        self.assertEqual(download['url'], '')
        self.assertIn('试听', download['reason'])

    def test_shorter_than_metadata_is_conservatively_trial(self):
        result = media_info(response(time=30000), '123', full_duration_ms=200000)
        self.assertTrue(result['trial'])
        self.assertEqual(result['duration_ms'], 30000)
        self.assertEqual(media_info(response(time=30000), '123', True, 200000)['url'], '')
        self.assertFalse(media_info(response(time=199000), '123', full_duration_ms=200000)['trial'])

    def test_unknown_and_unavailable_results_have_no_media_url(self):
        for raw in [dict(code=301), dict(code=200, data=[]), dict(code=200, data=[dict(id=999)]),
                    response(code=404, url=None), response(type='exe'), response(type='wav'),
                    response(size=-1), response(time=True), response(size=2 ** 40),
                    response(freeTrialInfo='null'), response(url='https://other.test/song.mp3')]:
            with self.subTest(raw=raw):
                result = media_info(raw, '123', download=True)
                self.assertTrue(result['unavailable'])
                self.assertEqual(result['url'], '')

    def test_service_direct_normal_endpoints_and_rights_not_fallback(self):
        paths = []
        def respond(request):
            paths.append(request.url)
            self.assertTrue(request.direct)
            self.assertEqual(request.cookie, '')
            if request.url.endswith('/download/url'):
                self.assertEqual(request.params, dict(id='123', br=128000))
                return dict(code=301)
            self.assertEqual(request.params, dict(br=128000, ids='[123]'))
            return response(code=404, url=None)
        service = Service()
        self.assertTrue(drive(service.media('123'), respond)['unavailable'])
        result = drive(service.media('123', download=True), respond)
        self.assertTrue(result['unavailable'])
        self.assertEqual(paths, ['https://music.163.com/api/song/enhance/player/url',
                                 'https://music.163.com/api/song/enhance/download/url'])

    def test_community_download_is_separate_and_metadata_checks_trial(self):
        requests = []
        def respond(request):
            requests.append(request)
            self.assertEqual(request.cookie, SESSION['cookie'])
            if request.url.endswith('/song/detail'):
                return dict(songs=[dict(song(123), dt=200000)])
            self.assertTrue(request.url.endswith('/song/download/url'))
            self.assertEqual(request.params, dict(id='123', br=128000))
            raw = response(time=30000)
            raw['data'] = raw['data'][0]
            return raw
        result = drive(Service(SESSION['api'], SESSION).media('123', download=True), respond)
        self.assertEqual(len(requests), 2)
        self.assertTrue(result['trial'])
        self.assertTrue(result['unavailable'])
        self.assertEqual(result['url'], '')
        self.assertFalse(any('/song/url' in request.url for request in requests))

    def test_expired_session_is_not_hidden_as_unavailable_media(self):
        def expired(request):
            raise SessionExpired('test expired')
        with self.assertRaises(SessionExpired):
            drive(Service(SESSION['api'], SESSION).media('123'), expired)
        with self.assertRaises(ApiError):
            next(Service().media('123', download=1))

    def test_media_permission_denied_with_valid_session_does_not_logout(self):
        for download in (False, True):
            for denied in ('exception', 301, 403):
                calls = []
                def respond(request):
                    calls.append(request.url)
                    if request.url.endswith('/login/status'):
                        return dict(code=200, data=dict(profile=dict(userId=77, nickname='测试用户')))
                    if denied == 'exception':
                        raise SessionExpired('simulated HTTP/JSON403')
                    return dict(code=denied)
                with self.subTest(download=download, denied=denied):
                    result = drive(Service(SESSION['api'], SESSION).media('123', download), respond)
                    self.assertTrue(result['unavailable'])
                    self.assertEqual(result['url'], '')
                    self.assertIn('账号仍有效', result['reason'])
                    self.assertIn('下载' if download else '播放', result['reason'])
                    self.assertEqual(len(calls), 2)
                    self.assertTrue(calls[-1].endswith('/login/status'))

    def test_permission_denied_then_missing_profile_still_expires(self):
        calls = []
        def respond(request):
            calls.append(request.url)
            if request.url.endswith('/login/status'):
                return dict(code=200, data=dict(profile=None))
            raise SessionExpired('simulated permission denied')
        with self.assertRaises(SessionExpired):
            drive(Service(SESSION['api'], SESSION).media('123', True), respond)
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
