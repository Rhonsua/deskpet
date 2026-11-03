"""Provider identity isolation in shared lyrics, beat caches and playback clocks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from deskpet.music.lyrics.store import LyricsStore, validate_source
from deskpet.music.beats import BeatController
from deskpet.music.tools.clock import playback_snapshot
from deskpet.app import MusicPanel

HASH = '0123456789ABCDEF0123456789ABCDEF'


class SharedMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lyric_sources_are_strict_and_cache_rows_are_separate(self):
        with TemporaryDirectory() as directory:
            store = LyricsStore(Path(directory) / 'lyrics.db')
            try:
                n = store.cache('netease', '123', '同名歌', '[00:00]网易云版本')
                k = store.cache('kugou', HASH, '同名歌', '[00:01]酷狗版本')
                self.assertNotEqual(n, k)
                store.bind('netease:123', n)
                store.bind('kugou:' + HASH, k)
                self.assertEqual(store.binding('netease:123')['body'], '[00:00]网易云版本')
                self.assertEqual(store.binding('kugou:' + HASH)['body'], '[00:01]酷狗版本')
                self.assertIsNone(store.cached_online(HASH))
                self.assertEqual(store.cached_online(HASH, 'kugou')['id'], k)
                for key in ('kugou:123', 'kugou:' + HASH.lower(), 'kugou:' + HASH + '?url=wrong'):
                    with self.assertRaises(ValueError):
                        validate_source(key)
            finally:
                store.close()

    def test_beat_cache_key_includes_platform_and_audio_identity(self):
        with TemporaryDirectory() as directory:
            beats = BeatController(directory)
            beats.restore_online('netease:123', 'same-audio-identity')
            first = beats._cache_path
            beats._write(first, {'bpm': 120, 'beats_ms': [0, 500, 1000]})
            self.assertFalse(beats.restore_online('kugou:' + HASH, 'same-audio-identity'))
            second = beats._cache_path
            self.assertNotEqual(first, second)
            self.assertFalse(beats.has_timing())
            self.assertTrue(beats.restore_online('netease:123', 'same-audio-identity'))
            self.assertTrue(beats.has_timing())
            beats.shutdown()

    def test_clock_tracks_actual_player_not_selected_browsing_platform(self):
        player = NS(current={'id': HASH, 'title': '酷狗样本'}, media_ready=True, trial_offset=0)
        panel = NS(playback_source='kugou', cloud_player=player,
                   _player=NS(values=dict(position=1234, duration=8000, state=1, status=5)),
                   engine=NS(ready=True, last_report=100))
        snapshot = playback_snapshot(panel, 101)
        self.assertTrue(snapshot.playing)
        self.assertEqual(snapshot.source_key, 'kugou:' + HASH)
        self.assertEqual(snapshot.position_ms, 1234)
        self.assertFalse(playback_snapshot(panel, 105).playing)

    def test_main_controls_route_to_kugou_and_local_selection_deactivates_it(self):
        from unittest.mock import Mock
        cloud = Mock()
        panel = NS(playback_source='kugou', cloud_player=cloud, settings=Mock())
        MusicPanel.toggle(panel)
        MusicPanel.step(panel, 1)
        cloud.toggle.assert_called_once()
        cloud.step.assert_called_once_with(1)
        panel.pet = NS(music_companion=NS(preparation=Mock()))
        panel.bilibili = NS(active=False)
        MusicPanel.activate_local(panel)
        self.assertEqual(panel.playback_source, 'local')
        cloud.deactivate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
