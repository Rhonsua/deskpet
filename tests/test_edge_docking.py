import unittest
from PySide6.QtCore import QPoint, QRect, QSize
from edge_docking import (clamp_position, dock_position, nearest_edge, pushed_edge,
                          edge_gap, keep_drag_docked, dock_ease)


class EdgeGeometryTests(unittest.TestCase):
    def setUp(self):
        self.bounds = QRect(-1920, -200, 1920, 1040)
        self.size = QSize(260, 310)

    def test_all_edges_and_corners(self):
        samples = [('left', QPoint(-1910, 80)), ('right', QPoint(-270, 80)),
                   ('top', QPoint(-900, -180)), ('bottom', QPoint(-900, 510))]
        for edge, point in samples:
            with self.subTest(edge=edge):
                self.assertEqual(nearest_edge(point, self.size, self.bounds), edge)
                snapped = dock_position(point, self.size, self.bounds, edge)
                self.assertTrue(self.bounds.contains(QRect(snapped, self.size)))
                self.assertEqual(nearest_edge(snapped, self.size, self.bounds, 0), edge)
        self.assertEqual(nearest_edge(QPoint(-1920, -200), self.size, self.bounds), 'left')

    def test_center_does_not_dock(self):
        self.assertEqual(nearest_edge(QPoint(-1000, 100), self.size, self.bounds), '')

    def test_clamps_to_available_area_including_last_pixel(self):
        self.assertEqual(clamp_position(QPoint(200, 1200), self.size, self.bounds),
                         QPoint(-260, 530))
        self.assertEqual(clamp_position(QPoint(-2500, -900), self.size, self.bounds),
                         self.bounds.topLeft())

    def test_resized_pet_stays_on_edge(self):
        size = QSize(390, 465)
        self.assertEqual(dock_position(QPoint(-260, 700), size, self.bounds, 'right'),
                         QPoint(-390, 375))

    def test_touching_edge_does_not_count_as_pushing(self):
        for edge in ('left', 'right', 'top', 'bottom'):
            point = dock_position(QPoint(-1000, 100), self.size, self.bounds, edge)
            self.assertEqual(pushed_edge(point, self.size, self.bounds), '')
            self.assertEqual(edge_gap(point, self.size, self.bounds, edge), 0)

    def test_pushing_beyond_each_edge(self):
        moves = {'left': QPoint(-24, 0), 'right': QPoint(24, 0),
                 'top': QPoint(0, -24), 'bottom': QPoint(0, 24)}
        for edge, delta in moves.items():
            point = dock_position(QPoint(-1000, 100), self.size, self.bounds, edge)
            self.assertEqual(pushed_edge(point + delta, self.size, self.bounds), edge)
            self.assertEqual(pushed_edge(point + delta, self.size, self.bounds, 25), '')

    def test_pull_dead_zone_scales_and_ignores_tangential_motion(self):
        for scale in (.75, 1, 1.5):
            for edge, inward in [('left', QPoint(1, 0)), ('right', QPoint(-1, 0)),
                                  ('top', QPoint(0, 1)), ('bottom', QPoint(0, -1))]:
                origin = dock_position(QPoint(-1000, 100), self.size, self.bounds, edge)
                threshold = round(36 * scale)
                self.assertTrue(keep_drag_docked(origin + inward * (threshold-1),
                    self.size, self.bounds, edge, self.bounds, scale))
                self.assertFalse(keep_drag_docked(origin + inward * threshold,
                    self.size, self.bounds, edge, self.bounds, scale))

    def test_crossing_to_another_monitor_releases_old_edge(self):
        origin = dock_position(QPoint(-1000, 100), self.size, self.bounds, 'right')
        self.assertFalse(keep_drag_docked(origin, self.size, self.bounds, 'right',
                                         QRect(0, 0, 2560, 1400)))

    def test_easing_is_bounded_monotonic_and_soft_at_both_ends(self):
        values = [dock_ease(i/100) for i in range(101)]
        self.assertEqual((values[0], values[-1]), (1, 0))
        self.assertTrue(all(a >= b for a, b in zip(values, values[1:])))
        self.assertLess(1-values[1], .001)
        self.assertLess(values[-2], .001)


if __name__ == '__main__':
    unittest.main()
