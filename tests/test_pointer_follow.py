import unittest
from pointer_follow import PointerFollow, apply_pointer


class PointerFollowTests(unittest.TestCase):
    def test_nearby_attention_eases_in_and_distant_pointer_eases_out(self):
        follow = PointerFollow()
        x, _, weight = follow.step(170, 0, .03)
        self.assertTrue(0 < x < 1 and 0 < weight < 1)
        for _ in range(90):
            follow.step(170, 0, 1/30)
        self.assertAlmostEqual(follow.x, 1)
        for _ in range(90):
            follow.step(900, 0, 1/30)
        self.assertLess(follow.weight, .0001)
        self.assertLess(abs(follow.x), .0001)

    def test_drag_and_resting_poses_ignore_pointer(self):
        base = {'ParamAngleX': 3, 'ParamBodyAngleX': 1, 'ParamEyeBallX': .2}
        for activity in ('lift', 'land', 'sleep', 'phone', 'head_rub', 'mouse_wave'):
            self.assertEqual(apply_pointer(base, activity, (1, 1, 1)), base)
        self.assertEqual(base, {'ParamAngleX': 3, 'ParamBodyAngleX': 1, 'ParamEyeBallX': .2})

    def test_singing_turn_is_not_overridden_by_nearby_pointer(self):
        base = {'ParamAngleX': 28, 'ParamBodyAngleX': 10, 'ParamEyeBallX': 0}
        result = apply_pointer(base, 'sing', (-1, 0, 1))
        self.assertEqual(result['ParamAngleX'], 28)
        self.assertEqual(result['ParamBodyAngleX'], 10)
        self.assertEqual(result['ParamEyeBallX'], -.65)
        result = apply_pointer(base, 'idle', (1, 0, 1))
        self.assertEqual(result['ParamAngleX'], 30)
        self.assertEqual(result['ParamBodyAngleX'], 10)


if __name__ == '__main__':
    unittest.main()
