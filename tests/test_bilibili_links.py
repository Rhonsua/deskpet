import json
import unittest
from bilibili_links import video_url, load_web_tracks, EndLatch


class BilibiliLinksTests(unittest.TestCase):
    def test_normalizes_video_links_and_part(self):
        self.assertEqual(video_url('http://m.bilibili.com/video/BV1xx411c7mu?p=2&share_source=copy#reply'),
                         'https://www.bilibili.com/video/BV1xx411c7mu/?p=2')
        self.assertEqual(video_url('https://bilibili.com/video/av170001/'),
                         'https://www.bilibili.com/video/av170001/')

    def test_rejects_non_video_and_lookalike_domains(self):
        for value in ('https://example.com/video/BV1xx411c7mu',
                      'https://www.bilibili.com.evil.test/video/BV1xx411c7mu',
                      'https://evil.test@www.bilibili.com/video/BV1xx411c7mu',
                      'javascript:alert(1)', 'file:///C:/private.mp3',
                      'https://www.bilibili.com/', 'https://live.bilibili.com/123',
                      'https://www.bilibili.com/bangumi/play/ep123', 'https://b23.tv/abcd',
                      'https://www.bilibili.com/video/BVbad',
                      'https://www.bilibili.com:1234/video/BV1xx411c7mu',
                      'https://www.bilibili.com/video/BV1xx411c7mu/other'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                video_url(value)

    def test_rejects_invalid_parts_and_credentials(self):
        for part in ('0', '-1', 'x', '1&p=2', '10001'):
            with self.subTest(part=part), self.assertRaises(ValueError):
                video_url('https://www.bilibili.com/video/BV1xx411c7mu/?p=' + part)

    def test_saved_tracks_deduplicate_and_reject_corrupt_links(self):
        data = [{'url': 'https://bilibili.com/video/av170001', 'title': '歌曲'},
                {'url': 'https://www.bilibili.com/video/av170001/?share=x'},
                {'url': 'https://example.com'}, None]
        self.assertEqual(len(load_web_tracks(json.dumps(data))), 1)
        self.assertEqual(load_web_tracks('bad json'), [])
        self.assertEqual(load_web_tracks('{}'), [])


class CompletionTests(unittest.TestCase):
    def test_only_one_end_for_current_token(self):
        latch = EndLatch()
        latch.reset('current')
        self.assertFalse(latch.accept({'token': 'old', 'ended': True, 'seen_playing': True}))
        self.assertFalse(latch.accept({'token': 'current', 'ended': True}))
        event = {'token': 'current', 'ended': True, 'seen_playing': True}
        self.assertTrue(latch.accept(event))
        self.assertFalse(latch.accept(event))
        latch.reset('next')
        self.assertFalse(latch.accept(event))
        self.assertTrue(latch.accept({**event, 'token': 'next'}))

    def test_pause_or_loading_does_not_end_track(self):
        latch = EndLatch()
        latch.reset('x')
        for event in ({'playing': False}, {'has_video': False}, {'error': 4}):
            self.assertFalse(latch.accept({'token': 'x', **event}))


if __name__ == '__main__':
    unittest.main()
