import unittest
from singing_choreography import footwork, PHRASES, CYCLE_SECONDS
from live2d_motion import MotionLibrary
from live2d_renderer import MODEL_ROOT


class SingingChoreographyTests(unittest.TestCase):
    def test_all_phrases_keep_one_support_foot_and_stay_in_authored_range(self):
        observed = set()
        for index in range(1921):
            step = footwork(index*.01)
            observed.add(step['phrase'])
            self.assertTrue(0 <= step['left'] <= 30)
            self.assertTrue(0 <= step['right'] <= 30)
            self.assertLessEqual(min(step['left'], step['right']), 1e-8)
            self.assertLessEqual(abs(step['weight']), 1.000001)
        self.assertEqual(observed, set(PHRASES))

    def test_phrase_boundaries_are_continuous_and_repeat_after_full_cycle(self):
        for t in (0, 4.8, 9.6, 14.4, CYCLE_SECONDS):
            a, b = footwork((t-1e-5) % CYCLE_SECONDS), footwork(t+1e-5)
            for key in ('left', 'right', 'weight'):
                self.assertAlmostEqual(a[key], b[key], places=5)
        for t in (.15, 1.7, 6.1, 11.25, 16.2):
            a, b = footwork(t), footwork(t+CYCLE_SECONDS)
            for key in ('left', 'right', 'weight'):
                self.assertAlmostEqual(a[key], b[key])

    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_singing_sampler_uses_supercycle_and_preserves_painted_pose(self):
        lib = MotionLibrary(MODEL_ROOT)
        values = []
        for t in (.2, 5, 9.8, 14.6):
            parameters, parts = lib.sample('sing', t)
            values.append(round(parameters['ParamLegLSwing'], 3))
            self.assertEqual(parts['LegLStraightSet'], 1)
            self.assertEqual(parts['LegRStraightSet'], 1)
            self.assertEqual(parts['LegLBentSet'], 0)
            self.assertEqual(parts['LegRBentSet'], 0)
        self.assertGreaterEqual(len(set(values)), 3)

    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_peak_weight_leans_towards_planted_foot_despite_yaw_sway_binding(self):
        lib = MotionLibrary(MODEL_ROOT)
        for i in range(1920):
            t = i*.01
            parameters, _ = lib.sample('sing', t)
            effective_roll = parameters['ParamBodyAngleX']*.2 + parameters['ParamBodyAngleZ']*.3
            if parameters['ParamLegLSwing'] >= 25:
                self.assertLess(effective_roll, 0)
            if parameters['ParamLegRSwing'] >= 25:
                self.assertGreater(effective_roll, 0)


if __name__ == '__main__':
    unittest.main()
