import unittest
from pet_behavior import PetBehavior


class BehaviorTests(unittest.TestCase):
    def test_each_mode_survives_drag_and_landing(self):
        for mode in ('idle', 'sleep', 'phone', 'sing'):
            with self.subTest(mode=mode):
                state = PetBehavior(mode)
                state.begin_drag()
                state.tick(100)
                self.assertEqual(state.mode, mode)
                self.assertEqual(state.activity, 'lift')
                state.end_drag()
                self.assertEqual(state.activity, 'land')
                state.tick(0.7)
                self.assertEqual(state.activity, mode)

    def test_feeding_timer_is_suspended_until_after_landing(self):
        state = PetBehavior('sleep')
        state.react('eat', 2.8)
        state.tick(1)
        state.begin_drag()
        state.tick(30)
        state.end_drag()
        state.tick(0.65)
        self.assertEqual(state.activity, 'eat')
        self.assertAlmostEqual(state.layers[-1].remaining, 1.8)
        state.tick(1.9)
        self.assertEqual(state.activity, 'sleep')

    def test_playback_changes_during_drag_are_not_overwritten_by_snapshot(self):
        state = PetBehavior()
        state.playing = True
        state.begin_drag()
        state.playing = False
        state.end_drag()
        state.tick(1)
        self.assertEqual(state.activity, 'idle')

    def test_latest_intent_during_drag_wins(self):
        state = PetBehavior('sleep')
        state.begin_drag()
        state.set_mode('phone')
        self.assertEqual(state.activity, 'lift')
        state.end_drag()
        state.tick(1)
        self.assertEqual(state.activity, 'phone')

    def test_repeated_drag_during_landing_still_resumes_feeding(self):
        state = PetBehavior('phone')
        state.react('eat', 2)
        for _ in range(3):
            state.begin_drag()
            state.tick(5)
            state.end_drag()
            state.tick(0.2)
        state.tick(1.5)
        self.assertEqual(state.activity, 'eat')
        state.tick(2)
        self.assertEqual(state.activity, 'phone')

    def test_edge_docking_can_finish_without_landing(self):
        state = PetBehavior('sleep')
        state.begin_drag()
        state.end_drag(landing=False)
        self.assertEqual(state.activity, 'sleep')

    def test_temporary_reply_and_turn_do_not_change_persistent_mode(self):
        state = PetBehavior('phone')
        for action in ('happy', 'poke', 'turn'):
            state.react(action, 2)
            state.tick(2.1)
            self.assertEqual(state.activity, 'phone')

    def test_reaction_queued_during_drag_runs_after_landing(self):
        state = PetBehavior('sing')
        state.begin_drag()
        state.react('happy', 1)
        self.assertEqual(state.activity, 'lift')
        state.end_drag()
        state.tick(0.7)
        self.assertEqual(state.activity, 'happy')
        state.tick(1)
        self.assertEqual(state.activity, 'sing')

    def test_invalid_saved_mode_falls_back(self):
        self.assertEqual(PetBehavior('unknown').mode, 'idle')

    def test_listen_mode_keeps_microphone_put_away_while_music_plays(self):
        state = PetBehavior('listen')
        state.playing = True
        state.begin_drag()
        state.end_drag()
        state.tick(1)
        self.assertEqual(state.activity, 'idle')


if __name__ == '__main__':
    unittest.main()
