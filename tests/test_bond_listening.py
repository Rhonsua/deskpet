import unittest
from deskpet.mods.bond.listening import Coverage


class CoverageTests(unittest.TestCase):
    def sample(self,tracker,position,seconds=1,source='a'):
        tracker.sample(dict(seconds=seconds,title='实际歌曲',track=dict(source=source,position=position,duration=60)))

    def test_complete_only_at_natural_end_once(self):
        c=Coverage()
        for p in range(1,60):self.sample(c,p)
        result=c.finish('a');self.assertEqual(result['title'],'实际歌曲');self.assertIsNone(c.finish('a'))

    def test_jump_to_end_not_a_full_listen(self):
        c=Coverage()
        for p in list(range(1,6))+list(range(55,60)):self.sample(c,p)
        self.assertIsNone(c.finish('a'))

    def test_no_audio_no_coverage_and_source_change_resets(self):
        c=Coverage();c.sample({'seconds':5});self.assertIsNone(c.finish('a'))
        for p in range(1,50):self.sample(c,p)
        for p in range(50,60):self.sample(c,p,source='b')
        self.assertIsNone(c.finish('b'))

    def test_rewind_does_not_accumulate_first_half_into_full(self):
        c=Coverage()
        for repeat in range(3):
            for p in range(1,35):self.sample(c,p)
        self.sample(c,60)
        self.assertIsNone(c.finish('a'))
