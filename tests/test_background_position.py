"""Viewport crop, direct manipulation, cancel, and persisted chat settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtCore import Qt, QSize, QSettings, QTimer, QPoint
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from deskpet.ui.background import BackgroundSurface, BackgroundPlacement, background_crop
from deskpet.ui.background_position import BackgroundPositionDialog


class BackgroundPositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_image(self, path):
        image = QImage(600, 200, QImage.Format_RGB32)
        for x in range(image.width()):
            color = QColor('red' if x < 200 else 'green' if x < 400 else 'blue')
            for y in range(image.height()):
                image.setPixelColor(x, y, color)
        image.save(str(path))

    def test_horizontal_alignment_changes_visible_content_and_zoom_stays_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'stripes.png';self.make_image(image)
            surface = BackgroundSurface();surface.resize(200, 200);surface.set_surface(image)
            for position, expected in ((0, 'red'), (50, 'green'), (100, 'blue')):
                surface.set_placement({'x': position})
                self.assertEqual(surface.surface_cover.toImage().pixelColor(100, 100), QColor(expected))
            surface.set_placement({'x': 100, 'y': 0, 'zoom': 300})
            surface.resize(500, 130);surface.show();self.app.processEvents()
            self.assertEqual(surface.surface_cover.size(), surface.size())
            crop = background_crop(surface.surface_image.size(), surface.size(), surface.surface_placement)
            self.assertGreaterEqual(crop.left(), 0)
            self.assertGreaterEqual(crop.top(), 0)
            self.assertLessEqual(crop.right(), 600)
            self.assertLessEqual(crop.bottom(), 200)
            self.assertAlmostEqual(crop.width() / crop.height(), 500 / 130)
            surface.close()

    def test_vertical_alignment_and_invalid_saved_values(self):
        top = background_crop(QSize(200, 600), QSize(200, 200), {'y': 0})
        bottom = background_crop(QSize(200, 600), QSize(200, 200), {'y': 100})
        self.assertEqual(top.top(), 0)
        self.assertEqual(bottom.bottom(), 600)
        self.assertEqual(BackgroundPlacement.read('broken'), BackgroundPlacement())
        self.assertEqual(BackgroundPlacement.read({'x': float('nan'), 'y': -50, 'zoom': 999}),
                         BackgroundPlacement(50, 0, 300))

    def test_drag_preview_matches_sliders_and_cancel_restores_background(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'stripes.png';self.make_image(image)
            surface = BackgroundSurface();surface.resize(500, 400);surface.set_surface(image)
            original = BackgroundPlacement(50, 50, 180);surface.set_placement(original)
            dialog = BackgroundPositionDialog(surface);dialog.show();self.app.processEvents()
            center = dialog.preview.image_rect().center().toPoint()
            QTest.mousePress(dialog.preview, Qt.LeftButton, pos=center)
            QTest.mouseMove(dialog.preview, center + QPoint(-25, 20))
            QTest.mouseRelease(dialog.preview, Qt.LeftButton, pos=center + QPoint(-25, 20))
            self.assertGreater(surface.surface_placement.x, original.x)
            self.assertLess(surface.surface_placement.y, original.y)
            self.assertEqual(dialog.sliders['x'].value(), surface.surface_placement.x)
            self.assertEqual(dialog.preview.placement, surface.surface_placement)
            dialog.sliders['zoom'].setValue(220)
            self.assertEqual(surface.surface_placement.zoom, 220)
            dialog.close()
            self.assertEqual(surface.surface_placement, original)
            surface.close()

    def test_chat_save_reopen_cancel_replace_and_clear(self):
        from deskpet.chat.window import ChatWindow
        with tempfile.TemporaryDirectory() as directory, patch('deskpet.chat.companion_runtime.CompanionRuntime'):
            root = Path(directory)
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            pet = SimpleNamespace(panel=SimpleNamespace(data_dir=root, settings=settings),
                                  variant='refined', character_pack=None, character_name='洛天依')
            (root / 'chat').mkdir()
            self.make_image(root / 'chat/background.png')
            window = ChatWindow(pet)
            self.assertTrue(window.background_position_button.isEnabled())
            chosen = BackgroundPlacement(80, 25, 170)

            def finish_dialog(accept):
                dialog = next(child for child in window.children() if isinstance(child, BackgroundPositionDialog))
                dialog.set_controls(chosen if accept else BackgroundPlacement(10, 90, 250))
                (dialog.accept if accept else dialog.reject)()

            try:
                QTimer.singleShot(0, lambda: finish_dialog(True))
                window.adjust_background_position()
                self.assertEqual(settings.value('chat/background_placement'), chosen.as_dict())
            finally:
                window.shutdown();window.close();window.deleteLater();self.app.processEvents()
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            pet.panel.settings = settings
            window = ChatWindow(pet)
            try:
                self.assertEqual(window.surface_placement, chosen)
                QTimer.singleShot(0, lambda: finish_dialog(False))
                window.adjust_background_position()
                self.assertEqual(window.surface_placement, chosen)
                self.assertEqual(settings.value('chat/background_placement'), chosen.as_dict())
                source = root / 'replacement.png';self.make_image(source)
                with patch('deskpet.chat.window.QFileDialog.getOpenFileName', return_value=(str(source), '')):
                    window.choose_background()
                self.assertEqual(window.surface_placement, BackgroundPlacement())
                self.assertTrue(window.background_position_button.isEnabled())
                window.clear_background()
                self.assertFalse(window.background_position_button.isEnabled())
                self.assertFalse(settings.contains('chat/background_placement'))
                self.assertTrue(window.surface_image.isNull())
            finally:
                window.shutdown();window.close()
