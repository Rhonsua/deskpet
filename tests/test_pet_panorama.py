import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from deskpet.ui.panorama import panorama_frame


class PanoramaRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_global_landmarks_keep_their_place_across_moves_and_dpi_changes(self):
        artwork = QPixmap(450, 300)
        artwork.fill(Qt.red)
        p = QPainter(artwork)
        p.fillRect(220, 0, 230, 300, Qt.blue)
        p.fillRect(210, 145, 12, 8, Qt.green)
        p.end()
        # Side-by-side monitors; the full desktop's 2.25:1 cover crop starts
        # at row 50 of the artwork. The green landmark sits near the seam.
        desktop = QRect(-600, -180, 900, 400)
        landmark = desktop.topLeft() + QPoint(432, 198)
        first = QRect(landmark.x() - 80, landmark.y() - 80, 160, 160)
        second = first.translated(30, 15)
        for dpr in (1., 1.5, 2.):
            def frame_and_sample(aperture, world):
                frame = panorama_frame(artwork, desktop, aperture, dpr).toImage()
                local = world - aperture.topLeft()
                return frame.pixelColor(round(local.x() * dpr), round(local.y() * dpr))

            self.assertEqual(frame_and_sample(first, landmark), QColor(Qt.green))
            self.assertEqual(frame_and_sample(second, landmark), QColor(Qt.green))
            self.assertEqual(frame_and_sample(second, second.center()), QColor(Qt.blue))

    def test_transparent_corners_soft_edge_and_screen_boundary(self):
        art = QPixmap(300, 200)
        art.fill(Qt.white)
        desktop = QRect(-60, 10, 300, 200)
        window = QRect(0, 20, 160, 160)
        image = panorama_frame(art, desktop, window).toImage()
        self.assertEqual(image.pixelColor(80, 80).alpha(), 255)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        profile = [image.pixelColor(80 + r, 80).alpha() for r in (48, 58, 66, 74, 79)]
        self.assertEqual(profile[0], 255)
        self.assertTrue(all(inner > outer for inner, outer in zip(profile, profile[1:])), profile)
        clipped = panorama_frame(art, desktop, QRect(-150, 20, 160, 160)).toImage()
        self.assertEqual(clipped.pixelColor(80, 80).alpha(), 0)
        self.assertEqual(clipped.pixelColor(95, 80).alpha(), 255)
