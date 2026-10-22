import unittest
from types import SimpleNamespace as Box
from music_tools.clock import playback_snapshot, bilibili_key, beat_values, apply_music_beat


class MusicClockTests(unittest.TestCase):
    def panel(self):
        values = dict(position=1250, duration=8000, state=1, status=5, error=0, playback_rate=1.5)
        return Box(playback_source='local', current_path=lambda: 'D:/music/example.mp3',
                   _player=Box(values=values), engine=Box(ready=True, last_report=100))

    def test_local_tracks_real_position_and_never_extrapolates(self):
        panel = self.panel()
        first = playback_snapshot(panel, 100)
        later = playback_snapshot(panel, 101)
        self.assertTrue(first.valid and first.playing)
        self.assertEqual(first.position_ms, later.position_ms)
        self.assertEqual(first.rate, 1.5)
        panel._player.values.update(position=250, state=2)
        paused = playback_snapshot(panel, 101)
        self.assertEqual(paused.position_ms, 250)
        self.assertFalse(paused.playing)
        self.assertTrue(paused.valid)
        self.assertFalse(playback_snapshot(panel, 104).valid)

    def test_unloaded_source_retains_key_without_starting_audio(self):
        panel = self.panel()
        panel._player = None
        current = playback_snapshot(panel, 100)
        self.assertTrue(current.source_key.startswith('local:'))
        self.assertFalse(current.valid)

    def test_web_part_switch_seek_and_expired_report(self):
        panel = self.panel()
        panel.playback_source = 'web'
        panel.bilibili = Box(active=True, current_url='https://www.bilibili.com/video/BV1xx411c7mu?p=2',
            metrics=dict(position=2.5, duration=9, playback_rate=2, ready_state=4), playing=True,
            last_report=100, title=Box(text=lambda: 'test'))
        current = playback_snapshot(panel, 100)
        self.assertEqual(current.source_key, 'bilibili:BV1xx411c7mu:2')
        self.assertEqual(current.position_ms, 2500)
        self.assertEqual(current.rate, 2)
        self.assertNotEqual(current.source_key, bilibili_key(panel.bilibili.current_url.split('?')[0]))
        panel.bilibili.metrics['seeking'] = True
        self.assertFalse(playback_snapshot(panel, 100).valid)
        panel.bilibili.metrics['seeking'] = False
        self.assertFalse(playback_snapshot(panel, 104).playing)
        panel.bilibili.active = False
        self.assertEqual(playback_snapshot(panel, 100).source_key, '')

    def test_bad_numbers_cannot_poison_animation(self):
        panel = self.panel()
        panel._player.values.update(position=float('nan'), duration=float('inf'), playback_rate='bad')
        current = playback_snapshot(panel, 100)
        self.assertEqual((current.position_ms, current.duration_ms, current.rate), (0, 0, 1))
        self.assertIsNone(beat_values(dict(available=True, beat_index=0, phase=float('nan'))))

    def test_beat_drives_one_foot_and_preserves_authored_pose(self):
        original = dict(ParamAngleX=18, ParamBodyAngleX=6, ParamBodyAngleZ=0, MicVisible=1)
        at_floor = apply_music_beat(original, dict(available=True, beat_index=0, phase=0))
        self.assertEqual((at_floor['ParamLegLSwing'], at_floor['ParamLegRSwing']), (0, 0))
        left = apply_music_beat(original, Box(available=True, beat_index=0, phase=.5))
        right = apply_music_beat(original, Box(available=True, beat_index=1, phase=.5))
        self.assertEqual((left['ParamLegLSwing'], left['ParamLegRSwing']), (22, 0))
        self.assertEqual((right['ParamLegLSwing'], right['ParamLegRSwing']), (0, 22))
        self.assertEqual(left['ParamAngleX'], original['ParamAngleX'])
        self.assertEqual(left['MicVisible'], 1)
        self.assertEqual(apply_music_beat(original, None), original)


if __name__ == '__main__':
    unittest.main()
