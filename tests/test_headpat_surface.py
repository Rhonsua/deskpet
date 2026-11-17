"""Expanded input surface lifecycle with isolated Qt widgets, no desktop input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from deskpet.ui.headpat_surface import HeadpatSurface


class SurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pet = QWidget()
        self.pet.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.pet.setGeometry(-500, 70, 260, 310)
        self.pet.head_region = QRegion(QRect(70, 10, 120, 110))
        self.pet.scale = 1
        self.pet.petting = True
        self.pet.glove_cursor_pose = 'overlay'
        self.pet.setCursor(Qt.CursorShape.BlankCursor)
        self.pet.end_petting = Mock(side_effect=self.stop)
        self.surface = HeadpatSurface(self.pet)
        self.pet.show()
        self.surface.sync(True)
        self.app.processEvents()
        self.addCleanup(self.pet.close)

    def stop(self):
        self.pet.petting = False
        self.surface.sync(False)

    def test_real_surface_extends_past_pet_without_resizing_or_moving_it(self):
        self.assertEqual(self.pet.geometry(), QRect(-500, 70, 260, 310))
        self.assertTrue(self.surface.geometry().contains(self.pet.mapToGlobal(QPoint(-20, 60))))
        self.assertTrue(self.surface.geometry().contains(self.pet.mapToGlobal(QPoint(280, 60))))
        self.assertEqual(self.surface.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.pet.move(100, 120)
        self.surface.sync(True)
        self.assertTrue(self.surface.geometry().contains(self.pet.mapToGlobal(QPoint(280, 60))))
        image = self.surface.grab().toImage()
        self.assertEqual(image.pixelColor(image.rect().center()).alpha(), 1)

    def test_inactive_or_unavailable_surface_is_hidden_and_restores_cursor(self):
        self.surface.sync(False)
        self.assertFalse(self.surface.isVisible())
        self.assertIsNone(self.surface.cursor_pose)
        self.pet.setCursor(Qt.CursorShape.ArrowCursor)
        self.pet.glove_cursor_pose = (0, 0)
        self.surface.sync(True)
        self.assertTrue(self.surface.isVisible())
        self.assertEqual(self.surface.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.pet.petting = False
        self.surface.sync(True)
        self.assertFalse(self.surface.isVisible())

    def test_right_click_exits_and_left_drag_does_not_move_pet(self):
        before = self.pet.geometry()
        QTest.mousePress(self.surface, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseMove(self.surface, QPoint(80, 30))
        QTest.mouseRelease(self.surface, Qt.MouseButton.LeftButton, pos=QPoint(80, 30))
        self.assertEqual(self.pet.geometry(), before)
        self.pet.end_petting.assert_not_called()
        QTest.mouseClick(self.surface, Qt.MouseButton.RightButton, pos=QPoint(80, 30))
        self.pet.end_petting.assert_called_once()
        self.assertFalse(self.surface.isVisible())


if __name__ == '__main__':
    unittest.main()
