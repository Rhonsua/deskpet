import unittest
from PySide6.QtCore import QRect
from deskpet.animation.crawl_movement import CYCLE_DURATION, distance
from deskpet.animation.crawl_trail import CrawlTrail


class CrawlTrailTests(unittest.TestCase):
    def test_stationary_pose_does_not_emit(self):
        trail = CrawlTrail()
        for i in range(50):
            trail.capture(QRect(100, 100, 200, 100), i*.15, i*.15)
        self.assertEqual(trail.frames, [])

    def test_actual_movement_extends_one_patch_without_sliding_tail(self):
        trail = CrawlTrail()
        trail.capture(QRect(100, 100, 200, 100), 0, 0)
        trail.capture(QRect(97, 100, 200, 100), 1.2, 1.2)
        frame = trail.frames[0]
        self.assertEqual(frame.rect, QRect(191, 127, 3, 68))
        fixed_tail = frame.rect.right()
        trail.capture(QRect(90, 100, 200, 100), 1.4, 1.4)
        self.assertEqual(trail.frames, [frame])
        self.assertEqual(frame.rect.width(), 10)
        self.assertEqual(frame.rect.right(), fixed_tail)
        snapshot = QRect(frame.rect)
        # Same pose position at a later time must not reveal a preset rectangle.
        trail.capture(QRect(90, 100, 200, 100), 2.4, 2.4)
        self.assertEqual(frame.visible_rect(2.4), snapshot)
        self.assertEqual(trail.opacity(frame, 2.4), .78)
        self.assertIsNone(frame.fade_at)

    def test_distance_not_time_controls_length(self):
        widths = []
        for pixels in (4, 19):
            trail = CrawlTrail()
            trail.capture(QRect(100, 100, 200, 100), 0, 0)
            trail.capture(QRect(100-pixels, 100, 200, 100), 1.8, 1.8)
            widths.append(trail.frames[0].rect.width())
        self.assertEqual(widths, [4, 19])

    def test_three_completed_cycles_then_five_second_fade(self):
        trail = CrawlTrail()
        first = None
        for i in range(253):
            elapsed = i/30
            trail.capture(QRect(300-round(distance(elapsed)), 100, 200, 100),
                          100+elapsed, elapsed)
            if trail.frames and first is None:
                first = trail.frames[0]
            if first is not None and elapsed < 3*CYCLE_DURATION:
                self.assertIsNone(first.fade_at)
                self.assertEqual(trail.opacity(first, 100+elapsed), .78)
        self.assertEqual(len(trail.frames), 3)
        frame = first
        self.assertEqual(frame.rect.width(), 48)
        self.assertAlmostEqual(frame.fade_at, 100+3*CYCLE_DURATION)
        snapshot = QRect(frame.rect)
        self.assertEqual(trail.opacity(frame, 108.4), .78)
        self.assertLess(trail.opacity(frame, 110.9), .78)
        self.assertGreater(trail.opacity(frame, 113.39), 0)
        self.assertEqual(trail.opacity(frame, 113.4), 0)
        self.assertEqual(frame.visible_rect(113.4), snapshot)
        trail.prune(113.4)
        self.assertNotIn(frame, trail.frames)

    def test_later_cycles_fade_in_order_without_dropping_live_ribbons(self):
        trail = CrawlTrail()
        seen = []
        for i in range(840):
            elapsed = i/30
            trail.capture(QRect(800-round(distance(elapsed)), 100, 200, 100),
                          elapsed, elapsed)
            for frame in trail.frames:
                if not any(frame is old for old in seen):
                    seen.append(frame)
            for frame in seen:
                if frame.fade_at is None or elapsed-frame.fade_at < trail.lifetime:
                    self.assertIn(frame, trail.frames)
        for index, frame in enumerate(seen):
            expected = (index+3)*CYCLE_DURATION
            if expected <= elapsed:
                self.assertAlmostEqual(frame.fade_at, expected)
            else:
                self.assertIsNone(frame.fade_at)

    def test_boundary_pixels_belong_to_finishing_cycle(self):
        trail = CrawlTrail()
        for elapsed in (0, 1.8, 2.65, 2.9):
            trail.capture(QRect(300-round(distance(elapsed)), 100, 200, 100),
                          elapsed, elapsed)
        self.assertEqual(len(trail.frames), 1)
        first = trail.frames[0]
        self.assertEqual(first.rect.width(), 48)
        self.assertIsNone(first.fade_at)
        snapshot = QRect(first.rect)
        trail.capture(QRect(300-round(distance(4.2)), 100, 200, 100), 4.2, 4.2)
        self.assertEqual(len(trail.frames), 2)
        self.assertEqual(first.rect, snapshot)
        self.assertIsNone(first.fade_at)
        self.assertEqual(trail.frames[1].rect.right()+1, first.rect.left())
        self.assertIsNone(trail.frames[1].fade_at)

    def test_interruption_preserves_emitted_area_and_fades_once(self):
        trail = CrawlTrail()
        trail.capture(QRect(100, 100, 200, 100), 0, 0)
        trail.capture(QRect(97, 100, 200, 100), 1.2, 1.2)
        frame = trail.frames[0]
        snapshot = QRect(frame.rect)
        trail.stop(2)
        trail.stop(3)
        self.assertEqual(frame.rect, snapshot)
        self.assertEqual(frame.fade_at, 2)
        trail.prune(7)
        self.assertFalse(trail.frames)

    def test_jump_clears_patch(self):
        trail = CrawlTrail()
        trail.capture(QRect(100, 100, 200, 100), 0, 0)
        trail.capture(QRect(97, 100, 200, 100), 1.2, 1.2)
        trail.capture(QRect(600, 100, 200, 100), 1.3, 1.3)
        self.assertFalse(trail.frames)
        self.assertIsNone(trail.previous)


if __name__ == '__main__':
    unittest.main()
