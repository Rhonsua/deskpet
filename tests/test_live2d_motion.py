import unittest

from deskpet.animation.live2d_motion import Curve, MotionLibrary
from deskpet.animation.live2d_renderer import MODEL_ROOT, POSE_SCALE
from deskpet.pet.behavior import PetBehavior


class Live2DMotionTests(unittest.TestCase):
    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_upper_body_uses_playback_phase_only_during_singing(self):
        library = MotionLibrary(MODEL_ROOT)
        beat = dict(available=True, beat_index=2, phase=.25)
        first, parts = library.sample('sing', .1, beat)
        later, later_parts = library.sample('sing', 7.8, beat)
        for key in ('ParamAngleX', 'ParamAngleY', 'ParamAngleZ', 'ParamBodyAngleX',
                    'ParamBodyAngleZ', 'ParamSingArm', 'ParamLegLSwing', 'ParamLegRSwing'):
            self.assertAlmostEqual(first[key], later[key], msg=key)
        self.assertEqual(parts, later_parts)
        for activity in ('idle', 'turn', 'sleep', 'phone', 'lift'):
            self.assertEqual(library.sample(activity, .4, beat), library.sample(activity, .4))

    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_singing_turn_has_clear_opposite_yaw_and_seamless_loop(self):
        library = MotionLibrary(MODEL_ROOT)
        front, _ = library.sample('sing', 0)
        left, left_parts = library.sample('sing', 1.2)
        right, right_parts = library.sample('sing', 3.6)
        end, _ = library.sample('sing', 4.8)
        self.assertAlmostEqual(front['ParamAngleX'], 0)
        self.assertAlmostEqual(left['ParamAngleX'], 28)
        self.assertAlmostEqual(right['ParamAngleX'], -28)
        self.assertAlmostEqual(left['ParamBodyAngleX'], 10)
        self.assertAlmostEqual(right['ParamBodyAngleX'], -10)
        self.assertEqual(front, end)
        self.assertEqual(left_parts, right_parts)
        self.assertEqual(left_parts['ArmLMicSet'], 1)
        self.assertEqual(left_parts['ArmROpenSet'], 1)

    def test_interpolation_and_pose_steps(self):
        self.assertEqual(Curve([0, 0, 0, 2, 1]).sample(1), .5)
        step = Curve([0, 0, 2, 2, 1])
        self.assertEqual(step.sample(1.999), 0)
        self.assertEqual(step.sample(2), 1)

    def test_psd2live_smooth_curves_and_mixed_segments(self):
        curve = Curve([0, 0, 1, .1, 0, .8, 1, 1, 1, 2, 2, 3])
        self.assertEqual(curve.sample(-1), 0)
        self.assertAlmostEqual(curve.sample(.4625), .5, places=6)
        self.assertEqual(curve.sample(1.5), 1)
        self.assertEqual(curve.sample(2), 3)
        with self.assertRaises(ValueError):
            Curve([0, 0, 1, .8, 0, .1, 1, 1, 1])

    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_every_activity_resets_other_pose_groups(self):
        library = MotionLibrary(MODEL_ROOT)
        groups = library.mapping['poseGroups']
        for activity in library.mapping['activities']:
            for seconds in (0, .5, 1.5, 2.79, 11.9):
                _, parts = library.sample(activity, seconds)
                for group in groups:
                    with self.subTest(activity=activity, seconds=seconds, group=group):
                        self.assertAlmostEqual(sum(parts[key] for key in group), 1)
                        self.assertTrue(all(value in (0, 1) for key, value in parts.items()))

    def test_sleep_resumes_its_clock_after_drag_and_food(self):
        state = PetBehavior('sleep')
        state.tick(3)
        state.react('eat', 2.8)
        state.tick(1)
        state.begin_drag()
        state.tick(10)
        state.end_drag()
        state.tick(.65)
        self.assertEqual(state.activity, 'eat')
        self.assertAlmostEqual(state.activity_elapsed, 1)
        state.tick(1.8)
        self.assertEqual(state.activity, 'sleep')
        self.assertAlmostEqual(state.activity_elapsed, 3)
        state.tick(.1)
        self.assertAlmostEqual(state.activity_elapsed, 3.1)

    def test_resting_head_sizes_match_standing_source_width(self):
        self.assertAlmostEqual(315 * POSE_SCALE['sleep'], 603)
        self.assertAlmostEqual(442 * POSE_SCALE['phone'], 603)
