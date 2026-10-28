import random
import unittest

from pet_behavior import PetBehavior
from teleport_controller import TeleportController, visual_at


class TeleportTests(unittest.TestCase):
    def controller(self, seed=0, deadline=0):
        self.clock = [1000.0]
        return TeleportController(deadline, monotonic=lambda: self.clock[0],
                                  wall_time=lambda: self.clock[0], rng=random.Random(seed))

    def test_vertical_targets_fit_work_area_and_use_both_directions(self):
        sides = set()
        for seed in range(100):
            controller = self.controller(seed)
            self.assertTrue(controller.start(400, -200, 900, height=310))
            self.assertTrue(-200 <= controller.destination <= 900)
            self.assertGreaterEqual(abs(controller.destination - 400), 123)
            sides.add(controller.destination > 400)
        self.assertEqual(sides, {True, False})

    def test_top_bottom_small_work_area(self):
        for y in (0, 700):
            controller = self.controller()
            self.assertTrue(controller.start(y, 0, 700, height=310))
            self.assertNotEqual(y, controller.destination)
        controller = self.controller()
        self.assertFalse(controller.start(0, 0, 60, height=310))
        self.assertEqual(controller.cooldown_until, 0)

    def test_cover_vanish_move_then_reveal(self):
        controller = self.controller()
        self.assertTrue(controller.start(0, 0, 700, height=310))
        moves = []
        for _ in range(100):
            destination = controller.step(.033)
            if destination is not None:
                moves.append(destination)
                self.assertEqual(controller.visual.person, 0)
                self.assertEqual(controller.visual.smoke, 0)
        self.assertEqual(moves, [controller.destination])
        self.assertFalse(controller.active)
        self.assertEqual(controller.visual.person, 1)
        self.assertGreater(visual_at(.30).smoke, .99)
        self.assertEqual(visual_at(.30).person, 1)
        self.assertEqual(visual_at(.45).person, 0)
        self.assertEqual(visual_at(1.20).person, 0)
        self.assertGreater(visual_at(1.20).smoke, .99)
        self.assertGreater(visual_at(1.65).person, 0)

    def test_persisted_cooldown_and_missed_busy_attempts(self):
        controller = self.controller()
        self.assertFalse(controller.automatic_due(True))
        self.clock[0] += 121
        self.assertFalse(controller.automatic_due(False))
        self.assertFalse(controller.automatic_due(True))
        self.clock[0] += 121
        self.assertTrue(controller.automatic_due(True))
        self.assertTrue(controller.start(0, 0, 700, height=310))
        self.assertGreaterEqual(controller.cooldown_until - self.clock[0], 600)
        deadline = controller.cooldown_until
        controller.cancel()
        self.assertEqual(controller.visual.person, 1)
        self.assertFalse(controller.start(0, 0, 700, height=310))
        restored = self.controller(deadline=deadline)
        self.assertFalse(restored.automatic_due(True))
        self.clock[0] = deadline + 1
        self.assertTrue(restored.automatic_due(True))

    def test_long_stall_cannot_skip_cover(self):
        controller = self.controller()
        controller.start(0, 0, 700, height=310)
        self.assertIsNone(controller.step(1000))
        self.assertLess(controller.elapsed, .2)
        controller.cancel()
        self.assertIsNone(controller.step(1))

    def test_temporary_layer_restores_saved_intent_and_is_interruptible(self):
        for mode in ('idle', 'listen'):
            behavior = PetBehavior(mode)
            self.assertTrue(behavior.begin_teleport())
            self.assertFalse(behavior.begin_walk('left'))
            self.assertEqual(behavior.mode, mode)
            behavior.end_teleport()
            self.assertEqual(behavior.activity, 'idle')
            self.assertEqual(behavior.mode, mode)
            behavior.begin_teleport()
            behavior.begin_drag()
            behavior.end_drag(False)
            self.assertFalse(behavior.layers)
            behavior.begin_teleport()
            behavior.set_mode('sleep')
            self.assertEqual(behavior.activity, 'sleep')
        self.assertFalse(PetBehavior('sleep').begin_teleport())

    def test_cloud_is_round_and_cached(self):
        from teleport_effects import cloud_image
        image = cloud_image(360, 360, 10, 10, 340, 340)
        self.assertIs(image, cloud_image(360, 360, 10, 10, 340, 340))
        # Inspect opaque extent, independent of antialiasing and row padding.
        from PySide6.QtGui import QImage
        alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
        raw, stride = bytes(alpha.constBits()), alpha.bytesPerLine()
        xs, ys = [], []
        for y in range(alpha.height()):
            for x in range(alpha.width()):
                if raw[y*stride+x] > 200:
                    xs.append(x)
                    ys.append(y)
        ratio = (max(xs)-min(xs)+1)/(max(ys)-min(ys)+1)
        self.assertTrue(.95 < ratio < 1.05, ratio)


if __name__ == '__main__':
    unittest.main()
