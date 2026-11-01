"""Pose-aware scaling must not drift again on the next animation frame."""
import unittest
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect, QSize
from deskpet.pet.desktop import DesktopPet


class GeometryPet:
    set_scale = DesktopPet.set_scale
    update_live2d_geometry = DesktopPet.update_live2d_geometry

    def __init__(self, activity):
        self.activity = activity
        self.scale = 1.0
        self.live2d_renderer = object()
        self.dock_edge = ''
        self.dragging = False
        self._pos = QPoint(1000, 700)
        self._size = QSize({'sleep': 400, 'phone': 320}.get(activity, 260), 310)
        self.panel = SimpleNamespace(settings=SimpleNamespace(setValue=lambda *_: None))

    def x(self): return self._pos.x()
    def y(self): return self._pos.y()
    def width(self): return self._size.width()
    def height(self): return self._size.height()
    def pos(self): return QPoint(self._pos)
    def size(self): return QSize(self._size)
    def resize(self, width, height): self._size = QSize(width, height)
    def move(self, pos): self._pos = QPoint(pos)
    def isVisible(self): return True
    def display_activity(self): return self.activity
    def screen_bounds(self): return QRect(0, 0, 3840, 2160)
    def stop_roaming(self): pass
    def prepare_frames(self): pass
    def update(self): pass


class ScalingTests(unittest.TestCase):
    def test_repeated_pose_scaling_preserves_ground_anchor(self):
        for activity in ('sleep', 'phone', 'idle', 'crawl'):
            with self.subTest(activity=activity):
                pet = GeometryPet(activity)
                start = pet.pos()
                anchor = (pet.x() + pet.width() / 2, pet.y() + 280)
                for scale in [1.5, .75, 1.25, 1.0] * 10:
                    pet.set_scale(scale)
                    self.assertLessEqual(abs(pet.x() + pet.width() / 2 - anchor[0]), .5)
                    self.assertLessEqual(abs(pet.y() + 280 * scale - anchor[1]), .5)
                    before = (pet.pos(), pet.size())
                    pet.update_live2d_geometry(activity)
                    self.assertEqual((pet.pos(), pet.size()), before)
                self.assertEqual(pet.pos(), start)
                self.assertEqual(pet.activity, activity)

    def test_enlarging_at_edge_stays_on_screen(self):
        pet = GeometryPet('sleep')
        pet.move(QPoint(0, 0))
        pet.set_scale(1.5)
        self.assertGreaterEqual(pet.x(), 0)
        self.assertGreaterEqual(pet.y(), 0)
        before = pet.pos()
        pet.update_live2d_geometry('sleep')
        self.assertEqual(pet.pos(), before)


if __name__ == '__main__':
    unittest.main()
