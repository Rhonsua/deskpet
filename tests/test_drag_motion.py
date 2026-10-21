import unittest
from drag_motion import DragSway, interaction_pose


class DragMotionTests(unittest.TestCase):
    def test_pickup_has_an_early_spring_and_settles_while_held(self):
        _, _, initial = interaction_pose('lift', 0)
        _, _, peak = interaction_pose('lift', .1)
        _, _, settle = interaction_pose('lift', 3)
        self.assertEqual(initial, 1)
        self.assertGreater(peak, 1.10)
        self.assertAlmostEqual(settle, 1.045, places=5)
        _, sx, sy = interaction_pose('land', .1)
        self.assertLess(sy, .94)
        self.assertGreater(sx, 1)

    def test_horizontal_motion_lags_then_settles_independent_of_frame_rate(self):
        endpoints = []
        for fps in (30, 60, 120):
            sway = DragSway()
            sway.move(30, .03)
            sway.step(1/fps)
            self.assertLess(sway.angle, 0)
            self.assertGreater(sway.angle, -1)
            for _ in range(round(fps*.5)-1):
                sway.step(1/fps)
            endpoints.append(sway.angle)
            sway.release()
            for _ in range(fps*3):
                sway.step(1/fps)
            self.assertLess(abs(sway.angle), .001)
        self.assertLess(max(endpoints)-min(endpoints), .1)


if __name__ == '__main__':
    unittest.main()
