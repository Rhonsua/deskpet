"""Lift timing and transition behavior without a Cubism or Qt context."""

import unittest

from lift_reaction import (
    FLAPS_PER_BURST, FLAPS_PER_SECOND, LIFT_RELEASE_SECONDS,
    LIFT_START_SECONDS, PAUSE_SECONDS, LiftReactionOverlay,
    sample_lift_reaction,
)


ARM_IDS = {'ParamLiftArmL', 'ParamLiftArmR'}
FACE_IDS = {
    'ParamLiftFear', 'ParamEyeLOpen', 'ParamEyeROpen',
    'ParamBrowLY', 'ParamBrowRY', 'ParamMouthOpenY',
}
PARAMETER_IDS = ARM_IDS | FACE_IDS | {'ParamArmLSwing', 'ParamArmRSwing'}
NEUTRAL = {
    'ParamEyeLOpen': 1.0, 'ParamEyeROpen': 1.0,
    'ParamBrowLY': 0.0, 'ParamBrowRY': 0.0,
    'ParamMouthOpenY': 0.0,
    'ParamArmLSwing': 7.0, 'ParamArmRSwing': -6.0,
}


class LiftReactionTests(unittest.TestCase):
    def test_onset_closes_eyes_and_starts_both_arms_in_015_seconds(self):
        start = sample_lift_reaction(0)
        middle = sample_lift_reaction(LIFT_START_SECONDS / 2)
        full = sample_lift_reaction(LIFT_START_SECONDS)
        self.assertEqual(start['ParamEyeLOpen'], 1)
        self.assertEqual(start['ParamLiftArmL'], 0)
        self.assertGreater(middle['ParamLiftArmL'], 0)
        self.assertGreater(middle['ParamEyeLOpen'], full['ParamEyeLOpen'])
        self.assertEqual(full['ParamEyeLOpen'], 0)
        self.assertEqual(full['ParamEyeROpen'], 0)
        self.assertEqual(full['ParamLiftFear'], 1)
        self.assertLess(full['ParamBrowLY'], 0)
        self.assertGreater(full['ParamMouthOpenY'], 0)
        self.assertEqual(full['ParamArmLSwing'], 0)
        self.assertEqual(full['ParamArmRSwing'], 0)

    def test_three_flaps_pause_and_loop_are_continuous_and_clock_based(self):
        burst = FLAPS_PER_BURST / FLAPS_PER_SECOND
        period = burst + PAUSE_SECONDS
        for offset in (0.02, 0.1, 0.3, burst - 0.02, burst + 0.1):
            first = sample_lift_reaction(LIFT_START_SECONDS + offset)
            next_period = sample_lift_reaction(LIFT_START_SECONDS + offset + period)
            self.assertAlmostEqual(first['ParamLiftArmL'], next_period['ParamLiftArmL'])
            self.assertAlmostEqual(first['ParamLiftArmR'], next_period['ParamLiftArmR'])
        pause = sample_lift_reaction(LIFT_START_SECONDS + burst + 0.1)
        self.assertAlmostEqual(pause['ParamLiftArmL'], 0.5)
        self.assertAlmostEqual(pause['ParamLiftArmR'], 0.5)
        for boundary in (burst, period):
            before = sample_lift_reaction(LIFT_START_SECONDS + boundary - 1e-5)
            after = sample_lift_reaction(LIFT_START_SECONDS + boundary + 1e-5)
            for arm in ARM_IDS:
                self.assertLess(abs(before[arm] - after[arm]), .001)
        # Sampling directly at a timestamp gives the same pose, however many
        # intermediate frames a caller did or did not render.
        overlay_a, overlay_b = LiftReactionOverlay(), LiftReactionOverlay()
        overlay_a.apply('idle', 0, NEUTRAL, PARAMETER_IDS)
        overlay_b.apply('idle', 0, NEUTRAL, PARAMETER_IDS)
        for frame in range(90):
            overlay_a.apply('lift', frame / 60, NEUTRAL, PARAMETER_IDS)
        actual = overlay_a.apply('lift', 1.5, NEUTRAL, PARAMETER_IDS)
        expected = overlay_b.apply('lift', 1.5, NEUTRAL, PARAMETER_IDS)
        for arm in ARM_IDS:
            self.assertAlmostEqual(actual[arm], expected[arm])

    def test_entry_blends_from_previous_rendered_face_and_cancels_old_swing(self):
        overlay = LiftReactionOverlay()
        previous = dict(NEUTRAL, ParamEyeLOpen=.2, ParamMouthOpenY=.7)
        overlay.apply('sing', 3, previous, PARAMETER_IDS)
        begin = overlay.apply('lift', 0, NEUTRAL, PARAMETER_IDS)
        self.assertAlmostEqual(begin['ParamEyeLOpen'], .2)
        self.assertAlmostEqual(begin['ParamMouthOpenY'], .7)
        self.assertEqual(begin['ParamArmLSwing'], 0)
        self.assertEqual(begin['ParamArmRSwing'], 0)
        later = overlay.apply('lift', LIFT_START_SECONDS, NEUTRAL, PARAMETER_IDS)
        self.assertEqual(later['ParamEyeLOpen'], 0)
        self.assertAlmostEqual(later['ParamMouthOpenY'], .6)

    def test_landing_releases_last_sample_by_025_then_clears(self):
        overlay = LiftReactionOverlay()
        overlay.apply('idle', 1, NEUTRAL, PARAMETER_IDS)
        lift = overlay.apply('lift', .31, NEUTRAL, PARAMETER_IDS)
        landing_start = overlay.apply('land', 0, NEUTRAL, PARAMETER_IDS)
        for key in ARM_IDS | {'ParamEyeLOpen', 'ParamMouthOpenY'}:
            self.assertAlmostEqual(landing_start[key], lift[key])
        midway = overlay.apply('land', LIFT_RELEASE_SECONDS / 2, NEUTRAL, PARAMETER_IDS)
        self.assertLess(midway['ParamLiftArmL'], lift['ParamLiftArmL'])
        self.assertGreater(midway['ParamEyeLOpen'], 0)
        done = overlay.apply('land', LIFT_RELEASE_SECONDS, NEUTRAL, PARAMETER_IDS)
        self.assertEqual(done['ParamLiftArmL'], 0)
        self.assertEqual(done['ParamLiftArmR'], 0)
        self.assertEqual(done['ParamLiftFear'], 0)
        self.assertEqual(done['ParamEyeLOpen'], 1)
        end = overlay.apply('land', .65, NEUTRAL, PARAMETER_IDS)
        self.assertEqual(end['ParamLiftArmL'], 0)
        self.assertEqual(end['ParamEyeLOpen'], 1)

    def test_repeat_lift_uses_last_rendered_value_and_clock_reset(self):
        overlay = LiftReactionOverlay()
        overlay.apply('idle', 0, NEUTRAL, PARAMETER_IDS)
        previous = overlay.apply('lift', .3, NEUTRAL, PARAMETER_IDS)
        restarted = overlay.apply('lift', 0, NEUTRAL, PARAMETER_IDS)
        for key in ARM_IDS | {'ParamEyeLOpen'}:
            self.assertAlmostEqual(restarted[key], previous[key])
        overlay.apply('land', .1, NEUTRAL, PARAMETER_IDS)
        releasing = dict(overlay.last_values)
        restarted = overlay.apply('lift', 0, NEUTRAL, PARAMETER_IDS)
        for key in ARM_IDS | {'ParamEyeLOpen'}:
            self.assertAlmostEqual(restarted[key], releasing[key])

    def test_edge_dock_pullback_has_its_own_smooth_entry_clock(self):
        overlay = LiftReactionOverlay()
        lifted = overlay.apply('lift', 1.0, NEUTRAL, PARAMETER_IDS)
        self.assertGreater(lifted['ParamLiftArmL'], 0)
        docked = overlay.apply('idle', 1.03, NEUTRAL, PARAMETER_IDS)
        self.assertEqual(docked['ParamLiftArmL'], 0)
        self.assertEqual(docked['ParamEyeLOpen'], 1)
        pulled = overlay.apply('lift', 1.06, NEUTRAL, PARAMETER_IDS)
        for key in ARM_IDS | {'ParamEyeLOpen', 'ParamMouthOpenY', 'ParamLiftFear'}:
            self.assertAlmostEqual(pulled[key], docked[key])
        halfway = overlay.apply('lift', 1.135, NEUTRAL, PARAMETER_IDS)
        self.assertGreater(halfway['ParamLiftArmL'], 0)
        self.assertGreater(halfway['ParamEyeLOpen'], 0)
        self.assertLess(halfway['ParamEyeLOpen'], 1)
        finished = overlay.apply('lift', 1.21, NEUTRAL, PARAMETER_IDS)
        target = sample_lift_reaction(1.21)
        for key in ARM_IDS | {'ParamEyeLOpen', 'ParamLiftFear'}:
            self.assertAlmostEqual(finished[key], target[key])

        # Re-entering just before a descending wave should never produce an
        # out-of-range intermediate arm value from the blend.
        for edge_time in (0.27, 0.46, 0.71, 1.15, 1.48, 1.75):
            overlay = LiftReactionOverlay()
            overlay.apply('lift', edge_time - .03, NEUTRAL, PARAMETER_IDS)
            overlay.apply('idle', edge_time, NEUTRAL, PARAMETER_IDS)
            for step in range(11):
                values = overlay.apply('lift', edge_time + .03 + step * .015,
                                       NEUTRAL, PARAMETER_IDS)
                for arm in ARM_IDS:
                    self.assertGreaterEqual(values[arm], 0)
                    self.assertLessEqual(values[arm], 1)

    def test_sleeping_mode_stays_closed_during_landing_and_after_resume(self):
        overlay = LiftReactionOverlay()
        sleep = dict(NEUTRAL, ParamEyeLOpen=0, ParamEyeROpen=0)
        overlay.apply('sleep', 4, sleep, PARAMETER_IDS)
        overlay.apply('lift', .4, NEUTRAL, PARAMETER_IDS)
        for elapsed in (0, .1, .25, .65):
            landing = overlay.apply('land', elapsed, NEUTRAL, PARAMETER_IDS,
                                    resume_activity='sleep')
            self.assertEqual(landing['ParamEyeLOpen'], 0)
            self.assertEqual(landing['ParamEyeROpen'], 0)
        resumed = overlay.apply('sleep', 4.1, sleep, PARAMETER_IDS,
                                resume_activity='sleep')
        self.assertEqual(resumed['ParamEyeLOpen'], 0)
        self.assertEqual(resumed['ParamLiftArmL'], 0)

    def test_unsupported_model_is_unchanged_and_abrupt_exit_clears_only_lift(self):
        overlay = LiftReactionOverlay()
        old = dict(NEUTRAL)
        self.assertIs(overlay.apply('lift', .8, old, FACE_IDS | {'ParamLiftArmL'}), old)
        self.assertEqual(old['ParamArmLSwing'], 7)
        overlay.apply('lift', .8, NEUTRAL, PARAMETER_IDS)
        sleep = dict(NEUTRAL, ParamEyeLOpen=0, ParamEyeROpen=0)
        after = overlay.apply('sleep', 0, sleep, PARAMETER_IDS)
        self.assertEqual(after['ParamEyeLOpen'], 0)
        self.assertEqual(after['ParamEyeROpen'], 0)
        self.assertEqual(after['ParamLiftArmL'], 0)
        self.assertEqual(after['ParamLiftArmR'], 0)
        self.assertEqual(after['ParamLiftFear'], 0)
        overlay.reset()
        self.assertEqual(overlay.last_values, {})
        self.assertEqual(overlay.release_values, {})
        self.assertIs(overlay.apply('idle', 0, old, PARAMETER_IDS, enabled=False), old)


if __name__ == '__main__':
    unittest.main()
