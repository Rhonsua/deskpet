import unittest
from mouse_interactions import (MouseInteractions, ActiveHeadPetting,
                                apply_active_petting, apply_mouse_reaction, REACTION_SECONDS)
from live2d_motion import MotionLibrary
from live2d_renderer import MODEL_ROOT
from pet_behavior import PetBehavior


class MouseInteractionTests(unittest.TestCase):
    def test_active_contact_responds_before_any_reward_and_stationary_relaxes(self):
        pat = ActiveHeadPetting()
        for _ in range(12):
            self.assertFalse(pat.step(0, 0, 1/60, contact=True))
        self.assertGreater(pat.strength, .3)
        self.assertEqual(pat.phase, 'contact')
        for _ in range(180):
            self.assertFalse(pat.step(0, 0, 1/60, contact=True))
        self.assertLess(pat.strength, .01)

    def test_active_slow_strokes_work_at_different_frame_rates_and_scales(self):
        for scale in (.75, 1, 1.5):
            strengths = []
            for fps in (10, 30, 60, 120):
                pat = ActiveHeadPetting()
                credits = 0
                for frame in range(4*fps):
                    # 60 px/s, including < 1 px per frame at high frame rates.
                    phase = (frame/fps) % 2
                    x = 60*(phase if phase <= 1 else 2-phase)*scale
                    credits += pat.step(x, 0, 1/fps, contact=True,
                                        scale=scale, head_width=115*scale)
                self.assertGreater(credits, 0)
                self.assertEqual(pat.phase, 'stroking')
                self.assertGreater(pat.strength, .75)
                strengths.append(pat.strength)
            self.assertLess(max(strengths)-min(strengths), .035)

    def test_active_jump_leave_and_reenter_do_not_credit_air_movement(self):
        pat = ActiveHeadPetting()
        pat.step(0, 0, .1, contact=True)
        self.assertFalse(pat.step(500, 0, .1, contact=True))
        self.assertIsNone(pat.previous)
        self.assertFalse(pat.step(-500, 0, .1, contact=True))
        for _ in range(6):
            self.assertFalse(pat.step(100, 100, .1, contact=False))
        self.assertLess(pat.strength, .005)
        self.assertFalse(pat.step(20, 0, .1, contact=True))
        self.assertEqual(pat.reward_distance, 0)

    def test_active_feedback_has_no_reward_cooldown_and_follows_direction(self):
        pat = ActiveHeadPetting()
        for i in range(30):
            pat.step(i*2, 0, 1/30, contact=True)
        self.assertGreater(pat.direction, .5)
        for i in range(30):
            pat.step(58-i*2, 0, 1/30, contact=True)
            self.assertGreater(pat.strength, .65)
        self.assertLess(pat.direction, -.5)
        parameters = {'ParamEyeLOpen': 1, 'ParamEyeROpen': 1, 'ParamAngleZ': 0}
        frame = apply_active_petting(parameters, 'idle', (pat.strength, pat.direction))
        self.assertLess(frame['ParamEyeLOpen'], .4)
        self.assertAlmostEqual(frame['ParamEyeLOpen'], .03)
        contact = apply_active_petting(parameters, 'idle', (.4, 0))
        self.assertGreater(contact['ParamEyeLOpen'], .3)
        self.assertLess(frame['ParamAngleZ'], 0)
        self.assertGreater(frame['ParamHeadPat'], .7)
        self.assertEqual(apply_active_petting(parameters, 'idle', (0, 0))['ParamHeadPat'], 0)
        self.assertEqual(apply_active_petting(parameters, 'sleep', (1, 1))['ParamHeadPat'], 0)

    def test_a_simple_pass_is_not_petting_but_back_and_forth_is(self):
        gestures = MouseInteractions()
        results = [gestures.step(x, 0, .1, in_head=True) for x in (0, 25, 50, 75)]
        self.assertNotIn('head_rub', results)
        results = [gestures.step(x, 0, .1, in_head=True) for x in (35, 70, 30)]
        self.assertIn('head_rub', results)
        results = [gestures.step(x, 0, .1, in_head=True) for x in (70, 30, 70, 30)]
        self.assertNotIn('head_rub', results)

    def test_hand_dwell_fires_once_per_visit_and_requires_cooldown(self):
        gestures = MouseInteractions()
        results = [gestures.step(0, 0, .1, near_hand=True) for _ in range(220)]
        self.assertEqual(results.count('mouse_wave'), 1)
        gestures.step(200, 0, .1)
        results = [gestures.step(0, 0, .1, near_hand=True) for _ in range(16)]
        self.assertEqual(results.count('mouse_wave'), 1)

    def test_drag_rest_or_disabled_setting_prevent_both_gestures(self):
        gestures = MouseInteractions()
        for i in range(200):
            self.assertIsNone(gestures.step((-1)**i*30, 0, .1,
                in_head=True, near_hand=True, enabled=False))
        self.assertEqual(gestures.hand_dwell, 0)

    def test_both_reactions_preserve_clock_and_playback_intent_after_drag(self):
        for activity, duration in REACTION_SECONDS.items():
            state = PetBehavior('sing')
            state.tick(8.3)
            state.react(activity, duration)
            state.tick(.4)
            state.begin_drag()
            state.tick(5)
            state.end_drag()
            state.tick(.65)
            self.assertEqual(state.activity, activity)
            self.assertAlmostEqual(state.activity_elapsed, .4)
            state.tick(duration-.4)
            self.assertEqual(state.activity, 'sing')
            self.assertAlmostEqual(state.activity_elapsed, 8.3)

    @unittest.skipUnless((MODEL_ROOT / 'action-map.json').is_file(), 'local model assets are not distributed with source')
    def test_native_motion_routes_return_to_idle_without_ghost_parts(self):
        lib = MotionLibrary(MODEL_ROOT)
        for activity, duration in REACTION_SECONDS.items():
            for t in (0, .35, .8, duration-.001, duration):
                parameters, parts = lib.sample(activity, t)
                for group in lib.mapping['poseGroups']:
                    self.assertEqual(sum(parts[key] for key in group), 1)
                self.assertTrue(all(value in (0, 1) for value in parts.values()))
                self.assertLessEqual(parameters['ParamEyeLOpen'], 1)
        a = apply_mouse_reaction({}, 'head_rub', 0)
        b = apply_mouse_reaction({}, 'head_rub', 2.2)
        self.assertEqual(a['ParamEyeLOpen'], 1)
        self.assertEqual(b['ParamEyeLOpen'], 1)


if __name__ == '__main__':
    unittest.main()
