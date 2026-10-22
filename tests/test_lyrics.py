"""Short synthetic lyric fixtures only; no downloaded songs or user data."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from music_lyrics.parser import parse_lrc, parse_srt, MAX_TEXT
from music_lyrics.store import LyricsStore, read_lyric_file, validate_source


class ParserTests(unittest.TestCase):
    def test_multiple_tags_repeats_translations_and_precision(self):
        doc = parse_lrc('[00:01.1][00:03.250]重复句\n[00:01.100]重复句\n[00:01.100]translated\n[00:04]最后')
        self.assertEqual(doc.starts, (1100, 3250, 4000))
        self.assertEqual(doc.at(1099), '')
        self.assertEqual(doc.at(1100), '重复句\ntranslated')
        self.assertEqual(doc.at(3250), '重复句')
        self.assertEqual(doc.at(99999), '最后')

    def test_global_offset_advances_without_clamping_distinct_negative_times(self):
        doc = parse_lrc('[offset:+1500]\n[00:00.000]早句\n[00:01.000]当前\n[00:02.000]下一句')
        self.assertEqual(doc.starts, (-1500, -500, 500))
        self.assertEqual(doc.at(0), '当前')
        self.assertEqual(parse_lrc('[offset:-1000]\n[00:00]延后').at(999), '')
        self.assertEqual(parse_lrc('[offset:-1000]\n[00:00]延后').at(1000), '延后')

    def test_empty_timestamp_clears_instrumental_gap(self):
        doc = parse_lrc('[00:00]第一句\n[00:02]\n[00:04]下一句')
        self.assertEqual(doc.at(1999), '第一句')
        self.assertEqual(doc.at(2000), '')
        self.assertEqual(doc.at(4000), '下一句')

    def test_seek_loop_and_unordered_lines_use_absolute_position(self):
        doc = parse_lrc('[00:10]后面\n[00:01]前面')
        self.assertEqual([doc.at(p) for p in (11000, 1000, 12000, 0, 1000)], ['后面', '前面', '后面', '', '前面'])

    def test_plain_text_metadata_and_html_remain_text(self):
        doc = parse_lrc('[ar:测试]\n[ti:测试标题]\n没有时间轴\n<img src="file:///invalid">')
        self.assertFalse(doc.timed)
        self.assertEqual(doc.at(2000), '')
        self.assertIn('<img', doc.plain_text)
        self.assertNotIn('[ar:', doc.plain_text)
        self.assertFalse(parse_lrc('[ti:纯音乐]').timed)

    def test_srt_exact_boundaries_gaps_and_multiline(self):
        doc = parse_srt('1\n00:00:01,250 --> 00:00:02,000\n第一行\n第二行\n\n2\n00:00:03.000 --> 00:00:04.000\n下一句')
        self.assertEqual(doc.at(1249), '')
        self.assertEqual(doc.at(1250), '第一行\n第二行')
        self.assertEqual(doc.at(2000), '')
        self.assertEqual(doc.at(3000), '下一句')
        self.assertEqual(doc.at(4000), '')

    def test_srt_invalid_and_limits(self):
        for text in ('not an SRT', '1\n00:00:04,000 --> 00:00:01,000\n反向', '1\n00:90:01,000 --> 00:90:02,000\n无效'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_srt(text)
        with self.assertRaises(ValueError):
            parse_lrc('x' * (MAX_TEXT + 1))
        with self.assertRaises(ValueError):
            parse_lrc('[offset:99999999999999999]\n[00:00]x')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lyrics-store-')
        self.root = Path(self.temp.name)
        self.store = LyricsStore(self.root / 'lyrics.db')
        self.source = 'local:' + str((self.root / '测试.mp3').resolve())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_metadata_cache_refresh_and_restart_binding(self):
        now = datetime(2026, 10, 22, 12, 0)
        lyric_id = self.store.cache('netease', '123', '人工样本', '[00:00]合成歌词', now=now)
        self.store.bind(self.source, lyric_id)
        self.store.offset(self.source, 350)
        updated = self.store.cache('netease', '123', '更新标题', '[00:01]更新歌词', now=now)
        self.assertEqual(updated, lyric_id)
        self.store.close()
        self.store = LyricsStore(self.root / 'lyrics.db')
        binding = self.store.binding(self.source)
        self.assertEqual((binding['source'], binding['song_id'], binding['title'], binding['fetched_at']),
                         ('netease', '123', '更新标题', now.isoformat()))
        self.assertEqual(binding['offset_ms'], 350)
        self.assertEqual(self.store.cached_online('123')['body'], '[00:01]更新歌词')
        self.assertIsNone(self.store.cached_online('999'))

    def test_different_binding_offsets_retained_without_title_guessing(self):
        first = self.store.cache('netease', '1', '同名', '[00:00]第一版本')
        second = self.store.cache('netease', '2', '同名', '[00:01]另一版本')
        self.store.bind(self.source, first)
        self.store.offset(self.source, 500)
        self.store.bind(self.source, second)
        self.assertEqual(self.store.binding(self.source)['offset_ms'], 0)
        self.store.offset(self.source, -100)
        self.store.bind(self.source, first)
        self.assertEqual(self.store.binding(self.source)['offset_ms'], 500)
        self.assertIsNone(self.store.binding('bilibili:BV1synthetic:1'))
        self.store.bind('bilibili:BV1synthetic:1', second)
        self.assertIsNone(self.store.binding('bilibili:BV1synthetic:2'))
        self.store.unbind(self.source)
        self.assertIsNone(self.store.binding(self.source))
        self.assertEqual(len(self.store.cached()), 2)

    def test_source_validation_and_sql_parameterization(self):
        for key in ('', 'local:relative.mp3', 'netease:0', 'bilibili:BV1synthetic:0', 'bilibili:BV1synthetic:',
                    'bilibili:BV1test:1', 'bilibili:av0:1', 'bilibili:av-1:1',
                    'bilibili:av123:10001', 'bilibili:BV1synthetic:10001'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_source(key)
        title = "x'); DROP TABLE lyrics;--"
        lyric_id = self.store.cache('netease', '1', title, '[00:00]纯文本')
        self.store.bind(self.source, lyric_id)
        self.assertEqual(self.store.binding(self.source)['title'], title)
        with self.assertRaises(ValueError):
            self.store.offset(self.source, 600001)

    def test_bilibili_bv_av_and_part_limits_match_video_url(self):
        from bilibili_links import video_url
        for video in ('BV1synthetic', 'av12345'):
            for part in (1, 2, 10000):
                key = f'bilibili:{video}:{part}'
                self.assertEqual(validate_source(key), key)
                self.assertIn(video, video_url(f'https://www.bilibili.com/video/{video}/?p={part}'))
                lyric_id = self.store.cache('netease', '1', '人工短样本', '[00:00]一句')
                self.store.bind(key, lyric_id)
                self.assertEqual(self.store.binding(key)['song_id'], '1')

    def test_netease_source_is_exact_positive_song_id(self):
        lyric_id = self.store.cache('netease', '123', '人工样本', '[00:00]一句')
        self.assertEqual(validate_source('netease:123'), 'netease:123')
        self.store.bind('netease:123', lyric_id)
        self.assertEqual(self.store.binding('netease:123')['id'], lyric_id)
        self.assertIsNone(self.store.binding('netease:124'))
        for key in ('netease:0', 'netease:01', 'netease:-1', 'netease:1?url=x', 'netease:' + '1' * 20):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_source(key)

    def test_utf8_utf16_and_gb18030_file_import(self):
        for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
            path = self.root / (encoding + '.lrc')
            path.write_bytes('[00:00]合成歌词'.encode(encoding))
            self.assertEqual(read_lyric_file(path), '[00:00]合成歌词')


if __name__ == '__main__':
    unittest.main()
