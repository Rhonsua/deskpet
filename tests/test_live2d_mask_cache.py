import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QRegion
from PySide6.QtWidgets import QApplication
from deskpet.pet.desktop import DesktopPet


class CountingPixmap:
    def __init__(self, pixmap):
        self.pixmap = pixmap
        self.calls = 0

    def cacheKey(self):
        return self.pixmap.cacheKey()

    def mask(self):
        self.calls += 1
        return self.pixmap.mask()


class MaskCacheTest(unittest.TestCase):
    def test_reuses_frame_and_invalidates_on_image_change(self):
        app = QApplication.instance() or QApplication([])
        state = SimpleNamespace(live2d_mask_key=None, live2d_mask_region=None)
        image = QPixmap(12, 12)
        image.fill(Qt.GlobalColor.transparent)
        frame = CountingPixmap(image)
        first = DesktopPet.live2d_mask(state, frame)
        self.assertEqual(first, QRegion(image.mask()))
        self.assertIs(first, DesktopPet.live2d_mask(state, frame))
        self.assertEqual(frame.calls, 1)
        image.fill(Qt.GlobalColor.white)
        updated = DesktopPet.live2d_mask(state, frame)
        self.assertEqual(updated, QRegion(image.mask()))
        self.assertNotEqual(first, updated)
        self.assertEqual(frame.calls, 2)


if __name__ == '__main__':
    unittest.main()
