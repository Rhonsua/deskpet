import random
import unittest
from unittest.mock import patch

from walk_controller import WalkController


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.wall = 10000.0

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


class WalkControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def controller(self, deadline=0):
        return WalkController(deadline, monotonic=lambda: self.clock.mono,
                              wall_time=lambda: self.clock.wall, rng=random.Random(7))

    def start(self, walk, **kwargs):
        options = dict(stride=40, cycle_seconds=1.2, cycles=3)
        options.update(kwargs)
        return walk.start(100, -300, 500, **options)

    def test_finite_both_directions_end_on_full_cycle_with_synced_distance(self):
        for direction in (-1, 1):
            walk = self.controller()
            self.assertTrue(self.start(walk, direction=direction))
            while walk.active:
                point = walk.step(1 / 60)
                self.assertAlmostEqual(abs(point - 100), walk.elapsed * (40 / 1.2))
            self.assertAlmostEqual(walk.x, 100 + direction * 120)
            self.assertAlmostEqual(walk.elapsed, 3.6)
            self.assertLess(min(walk.phase, 1 - walk.phase), 1e-9)
            self.assertIsNone(walk.step(.1))

    def test_frame_rate_independent_and_scale_affects_distance_not_gait(self):
        samples = []
        for fps in (30, 60, 120):
            walk = self.controller()
            self.start(walk, direction=1, scale=2)
            for _ in range(fps):
                walk.step(1 / fps)
            samples.append((walk.x, walk.elapsed))
        for sample in samples[1:]:
            self.assertAlmostEqual(sample[0], samples[0][0])
            self.assertAlmostEqual(sample[1], samples[0][1])
        self.assertAlmostEqual(samples[0][0] - 100, samples[0][1] * 80 / 1.2)

    def test_long_pause_cannot_jump_or_desynchronize_animation(self):
        walk = self.controller()
        self.start(walk, direction=1)
        walk.step(300)
        self.assertLessEqual(walk.x - 100, 40 / 1.2 * 2.6 * .1)
        self.assertLessEqual(walk.elapsed, .26)
        before = walk.x
        walk.step(float('nan'))
        walk.step(-1)
        self.assertEqual(walk.x, before)

    def test_cruising_speed_and_animation_both_increase_another_30_percent(self):
        walk = self.controller()
        self.start(walk, direction=1)
        for _ in range(30):
            walk.step(1 / 60)
        x, elapsed = walk.x, walk.elapsed
        walk.step(.1)
        self.assertAlmostEqual(walk.x - x, (40 / 1.2) * 2.0 * 1.3 * .1)
        self.assertAlmostEqual(walk.elapsed - elapsed, .2 * 1.3)

    def test_automatic_route_randomizes_within_manual_distance_range(self):
        for base, available in ((2, 100), (3, 100), (4, 100), (3, 5), (3, 1)):
            manual_cycles = min(base * 3, available)
            low = max(1, (manual_cycles + 1) // 2)
            high = min(available, manual_cycles * 2)
            for chosen in (low, high):
                walk = self.controller()
                with patch.object(walk._rng, 'randint', side_effect=[base, chosen]) as draw:
                    self.assertTrue(walk.start(0, 0, available * 40, stride=40,
                                               cycle_seconds=1.2, automatic=True))
                    self.assertEqual(draw.call_args_list[-1].args, (low, high))
                for _ in range(1000):
                    if not walk.active:
                        break
                    walk.step(.05)
                self.assertFalse(walk.active)
                self.assertAlmostEqual(walk.x, chosen * 40)
                self.assertGreaterEqual(walk.x, manual_cycles * 40 * .5)
                self.assertLessEqual(walk.x, min(available * 40, manual_cycles * 40 * 2))
                self.assertLess(min(walk.phase, 1 - walk.phase), 1e-8)

    def test_default_route_triples_distance_but_stays_inside_screen(self):
        for right, expected in ((1000, 360), (300, 200)):
            walk = self.controller()
            with patch.object(walk._rng, 'randint', return_value=3):
                self.assertTrue(walk.start(100, -1000, right, stride=40,
                                           cycle_seconds=1.2, direction=1))
            for _ in range(2000):
                if not walk.active:
                    break
                self.assertLessEqual(walk.step(.01), right)
            self.assertFalse(walk.active)
            self.assertAlmostEqual(walk.x - 100, expected)
            self.assertAlmostEqual(walk.elapsed, expected / 40 * 1.2)

    def test_only_feasible_direction_is_chosen_and_small_spaces_reject(self):
        walk = self.controller()
        self.assertTrue(walk.start(-300, -300, -200, stride=40, cycle_seconds=1))
        self.assertEqual(walk.direction, 1)
        while walk.active:
            self.assertLessEqual(walk.step(.1), -200)
        walk.cancel()
        self.assertFalse(walk.start(0, -10, 10, stride=40, cycle_seconds=1))
        self.assertEqual(walk.cooldown_until, 0)

    def test_invalid_options_fail_without_consuming_cooldown(self):
        for options in ({'stride': 0}, {'cycle_seconds': float('inf')},
                        {'scale': -1}, {'direction': True}, {'cycles': .5}):
            walk = self.controller()
            self.assertFalse(self.start(walk, automatic=True, **options))
            self.assertEqual(walk.cooldown_until, 0)

    def test_cancellation_discards_route_but_not_auto_cooldown(self):
        walk = self.controller()
        self.assertTrue(self.start(walk, automatic=True))
        deadline = walk.cooldown_until
        self.assertGreaterEqual(deadline - self.clock.wall, 600)
        walk.step(.1)
        elapsed = walk.elapsed
        walk.cancel()
        self.assertIsNone(walk.step(.1))
        self.assertEqual(walk.elapsed, elapsed)
        self.assertEqual(walk.cooldown_until, deadline)
        self.assertFalse(self.start(walk, automatic=True))
        self.clock.advance(599)
        self.assertFalse(walk.automatic_due())

    def test_manual_bypasses_and_preserves_auto_deadline(self):
        walk = self.controller()
        self.start(walk, automatic=True)
        deadline, remaining = walk.cooldown_until, walk.cooldown_remaining
        walk.cancel()
        self.assertTrue(self.start(walk))
        self.assertEqual(walk.cooldown_until, deadline)
        self.assertEqual(walk.cooldown_remaining, remaining)
        walk.cancel()
        self.assertFalse(walk.automatic_due())

    def test_restart_restores_remaining_cooldown_not_route(self):
        walk = self.controller()
        self.start(walk, automatic=True)
        self.clock.advance(90)
        reopened = self.controller(walk.cooldown_until)
        self.assertFalse(reopened.active)
        self.assertAlmostEqual(reopened.cooldown_remaining, walk.cooldown_remaining)
        self.assertFalse(reopened.automatic_due())
        self.clock.advance(reopened.cooldown_remaining)
        self.assertTrue(reopened.automatic_due())

    def test_wall_clock_changes_during_session_do_not_shorten_cooldown(self):
        walk = self.controller()
        self.start(walk, automatic=True)
        walk.cancel()
        before = walk.cooldown_remaining
        self.clock.wall += 100000
        self.assertEqual(walk.cooldown_remaining, before)
        self.assertFalse(walk.automatic_due())

    def test_busy_expired_attempt_is_discarded_and_attempts_are_not_per_frame(self):
        walk = self.controller()
        self.clock.advance(100)
        self.assertFalse(walk.automatic_due(eligible=False))
        self.assertFalse(walk.automatic_due())
        self.clock.advance(100)
        self.assertTrue(walk.automatic_due())
        for _ in range(100):
            self.assertFalse(walk.automatic_due())
        self.assertEqual(walk.cooldown_until, 0)

    def test_changed_screen_bounds_stop_without_crossing_edge(self):
        walk = self.controller()
        self.start(walk, direction=1)
        walk.step(.1)
        self.assertEqual(walk.step(.1, left=-500, right=-100), -100)
        self.assertFalse(walk.active)
        self.start(walk, direction=1)
        for _ in range(30):
            point = walk.step(.1, right=115)
            if point is not None:
                self.assertLessEqual(point, 115)
        self.assertEqual(walk.x, 115)
        self.assertFalse(walk.active)


if __name__ == '__main__':
    unittest.main()
