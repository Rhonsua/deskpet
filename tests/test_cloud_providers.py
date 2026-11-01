"""Synthetic cloud routing: identities, stale playback, and download permissions."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path
import unittest

from PySide6.QtCore import QCoreApplication, QObject, Signal

from deskpet.music.netease.download_queue import NeteaseDownloads
from deskpet.music.netease.downloads import Downloader, safe_stem
from deskpet.music.netease.playback import NeteasePlayback
from deskpet.music.tools.cloud_providers import clean_tracks, track_argument
from deskpet.music.kugou.service import ApiError, SessionExpired

HASH = 'ABCDEF0123456789ABCDEF0123456789'
TRACK = dict(id=HASH, hash=HASH, album_id='17', title='测试曲目', artists='测试', duration=120, album_audio_id='45', pay_type=0)


def result(operation):
    try:
        next(operation)
    except StopIteration as done:
        return done.value
    raise AssertionError('synthetic generator unexpectedly requested IO')


class Service:
    def __init__(self, trial=False):
        self.calls = []
        self.trial = trial
        self.song_error = None

    def media(self, item, download=False):
        self.calls.append(('media', item, download))
        if False:
            yield
        return dict(id=item['id'], trial=self.trial, unavailable=False,
                    url='https://fsandroid.tx.kugou.com/test.mp3', extension='mp3')

    def song(self, item):
        self.calls.append(('song', item))
        if self.song_error:
            raise self.song_error
        if False:
            yield
        return dict(id=item['id'], title=item['title'], lrc='[00:00]测试歌词')


class FakeClient(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.operation = None
        self.cancel_count = 0

    def run(self, kind, operation):
        self.cancel()
        self.kind, self.operation = kind, operation

    def cancel(self):
        self.cancel_count += 1
        if self.operation is not None:
            self.operation.close()
            self.operation = None


class Cloud(QObject):
    sessionChanged = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.set_playback_status = Mock()
        self._failed = Mock()

    def _service(self):
        return self.service


class CloudProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_track_identity_and_album_context(self):
        tracks = clean_tracks([dict(TRACK, id=HASH.lower(), hash=HASH.lower()), TRACK], 'kugou')
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0], TRACK)
        self.assertEqual(track_argument(tracks[0], 'kugou'), TRACK)
        self.assertEqual(track_argument(dict(id='123')), '123')
        for invalid in ('123', 'f'*31, 'g'*32):
            with self.assertRaises(ValueError):
                clean_tracks([dict(id=invalid)], 'kugou')
        with self.assertRaises(ValueError):
            clean_tracks([TRACK], 'unknown')

    def test_download_uses_complete_track_and_permission_endpoint(self):
        service = Service()
        prepared = result(NeteaseDownloads._prepare(service, TRACK, False, 'kugou'))
        self.assertEqual(service.calls, [('media', TRACK, True), ('song', TRACK)])
        self.assertEqual(prepared['lrc'], '[00:00]测试歌词')
        service = Service(trial=True)
        prepared = result(NeteaseDownloads._prepare(service, TRACK, False, 'kugou'))
        self.assertEqual(service.calls, [('media', TRACK, True)])
        self.assertEqual(prepared['lrc'], '')
        self.assertTrue(prepared['media']['trial'])

    def test_kugou_lyrics_only_and_expiry(self):
        service = Service()
        result(NeteaseDownloads._prepare(service, TRACK, True, 'kugou'))
        self.assertEqual(service.calls, [('song', TRACK)])
        service.song_error = ApiError('失败')
        prepared = result(NeteaseDownloads._prepare(service, TRACK, False, 'kugou'))
        self.assertEqual(prepared['lrc'], '')
        self.assertTrue(prepared['media']['url'])
        service.song_error = SessionExpired('过期')
        with self.assertRaises(SessionExpired):
            result(NeteaseDownloads._prepare(service, TRACK, False, 'kugou'))

    def test_mismatched_media_does_not_become_download(self):
        class WrongService(Service):
            def media(self, item, download=False):
                media = yield from super().media(item, download)
                media['id'] = '0'*32
                return media
        with self.assertRaises(ApiError):
            result(NeteaseDownloads._prepare(WrongService(), TRACK, False, 'kugou'))

    def test_play_other_provider_cancels_inflight_and_stale_ready(self):
        companion = QObject()
        panel = SimpleNamespace(queue=SimpleNamespace(mode='order'), playback_source='local',
                                bilibili=SimpleNamespace(active=False), player=Mock(), _player=object(),
                                pet=SimpleNamespace(playing=False), status=Mock(), song_meta=Mock(),
                                set_song_title=Mock(), ensure_audio=Mock())
        companion.pet = SimpleNamespace(panel=panel)
        callbacks = []
        companion.preparation = SimpleNamespace(cancel=Mock(), online=lambda *a, **kw: callbacks.append(a[2]))
        companion.lyrics = SimpleNamespace(import_online=Mock())
        companion.tick = Mock()
        with patch('deskpet.music.netease.playback.Client', FakeClient), \
             patch('deskpet.music.netease.playback.client_class', return_value=FakeClient):
            kugou = NeteasePlayback(companion, Cloud(Service()), 'kugou')
            netease = NeteasePlayback(companion, Cloud(SimpleNamespace(media=lambda item: (_ for _ in ()))))
        companion.stop_other_cloud = lambda provider: [p.deactivate() for p in (kugou, netease) if p.provider != provider]
        try:
            kugou.play([TRACK])
            self.assertTrue(kugou.active)
            kugou._resolved(kugou._request_kind('media'), dict(id=HASH, url='https://fsandroid.tx.kugou.com/test.mp3'))
            self.assertEqual(len(callbacks), 1)
            old_media_kind = kugou.client.kind
            old_lyric_kind = kugou.lyric_client.kind
            kugou._lyrics(kugou._request_kind('lyrics'), dict(TRACK, lrc='[00:00]测试歌词'))
            companion.lyrics.import_online.assert_called_once_with(
                HASH, TRACK['title'], '[00:00]测试歌词', 'kugou:' + HASH, provider='kugou')
            # Browsing another provider changes no playback source.
            panel.browsing_provider = 'netease'
            self.assertTrue(kugou.active)
            netease.play([dict(id='123', title='另一首')])
            self.assertIsNone(kugou.current)
            self.assertIsNone(kugou.client.operation)
            panel.player.reset_mock()
            callbacks[0]()
            kugou._resolved(kugou._request_kind('media'), dict(id=HASH, url='https://fsandroid.tx.kugou.com/test.mp3'))
            panel.player.setSource.assert_not_called()
            panel.player.play.assert_not_called()
            self.assertTrue(netease.active)
            kugou.play([TRACK])
            panel.player.reset_mock()
            companion.lyrics.import_online.reset_mock()
            before = len(callbacks)
            kugou.client.completed.emit(old_media_kind, dict(id=HASH, url='https://fsandroid.tx.kugou.com/test.mp3'))
            kugou.lyric_client.completed.emit(old_lyric_kind, dict(TRACK, lrc='[00:00]旧账号歌词'))
            kugou.client.failed.emit(old_media_kind, '旧请求失败', True)
            self.assertEqual(len(callbacks), before)
            companion.lyrics.import_online.assert_not_called()
            panel.player.setSource.assert_not_called()
            kugou.cloud._failed.assert_not_called()
        finally:
            kugou.deactivate()
            netease.deactivate()

    def test_provider_download_validator_and_final_response(self):
        validator = Mock(side_effect=ValueError('wrong provider'))
        downloader = Downloader(validator=validator)
        failures = []
        downloader.failed.connect(failures.append)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            downloader.start('https://m1.music.126.net/test.mp3', directory, 'test', 'mp3')
        self.assertTrue(failures)
        self.assertIsNone(downloader.reply)
        reply = Mock()
        reply.url.return_value.toString.return_value = 'https://example.test/redirect.mp3'
        downloader.reply = reply
        self.assertFalse(downloader._headers(reply))
        self.assertIsNone(downloader.reply)
        reply.abort.assert_called_once()
        prefix = '[kugou-' + HASH + '] '
        self.assertTrue(safe_stem(prefix + '长标题'*100).startswith(prefix))


if __name__ == '__main__':
    unittest.main()
