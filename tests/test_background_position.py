"""Viewport crop, direct manipulation, cancel, and persisted chat settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from threading import Event
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

    def wait_image(self, surface):
        for _ in range(200):
            if not surface.surface_image.isNull():
                return
            QTest.qWait(10)
        self.fail('background image did not load')

    def test_delayed_old_load_cannot_replace_new_image_or_closed_window(self):
        from deskpet.ui.background import _ImageLoader
        started, release = Event(), Event()
        def load(loader):
            if loader.path == 'slow':
                started.set()
                release.wait(5)
            image = QImage(4, 4, QImage.Format_RGB32)
            image.fill(QColor('red' if loader.path == 'slow' else 'blue'))
            loader.signals.finished.emit(loader.generation, image)
        with patch.object(_ImageLoader, 'run', load):
            surface = BackgroundSurface()
            try:
                surface.set_surface('slow')
                self.assertTrue(started.wait(5))
                surface.set_surface('fast')
                self.wait_image(surface)
                release.set()
                QTest.qWait(100)
                self.assertEqual(surface.surface_image.toImage().pixelColor(0, 0), QColor('blue'))
                started.clear(); release.clear()
                surface.set_surface('slow')
                self.assertTrue(started.wait(5))
                surface.close()
                release.set()
                QTest.qWait(100)
                self.assertTrue(surface.surface_image.isNull())
                surface.show()
                self.wait_image(surface)
                self.assertEqual(surface.surface_image.toImage().pixelColor(0, 0), QColor('red'))
            finally:
                release.set()
                surface.close()

    def test_background_loader_limits_dimensions_before_decode(self):
        from deskpet.ui.background import _ImageLoader
        reader = MagicMock()
        reader.size.return_value = QSize(8000, 4000)
        reader.read.return_value = QImage()
        with patch('deskpet.ui.background.QImageReader', return_value=reader):
            _ImageLoader('large', 1).run()
        reader.setAutoTransform.assert_called_once_with(True)
        reader.setScaledSize.assert_called_once_with(QSize(4096, 2048))
        reader.read.assert_called_once()
        reader.reset_mock()
        reader.size.return_value = QSize(10001, 10000)
        with patch('deskpet.ui.background.QImageReader', return_value=reader):
            _ImageLoader('too-large', 2).run()
        reader.read.assert_not_called()

    def test_horizontal_alignment_changes_visible_content_and_zoom_stays_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'stripes.png';self.make_image(image)
            surface = BackgroundSurface();surface.resize(200, 200);surface.set_surface(image)
            self.wait_image(surface)
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
            self.wait_image(surface)
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
            self.wait_image(window)
            window.tabs.setCurrentIndex(window.work_index)
            self.assertTrue(window.background_position_button.isEnabled())
            chosen = BackgroundPlacement(80, 25, 170)

            def finish_dialog(accept):
                dialog = next(child for child in window.children() if isinstance(child, BackgroundPositionDialog))
                dialog.set_controls(chosen if accept else BackgroundPlacement(10, 90, 250))
                (dialog.accept if accept else dialog.reject)()

            try:
                QTimer.singleShot(0, lambda: finish_dialog(True))
                window.adjust_background_position()
                self.assertEqual(settings.value('chat/background_placements'), {'work': chosen.as_dict()})
                window.tabs.setCurrentIndex(0)
                self.assertEqual(window.surface_placement, BackgroundPlacement())
                window.tabs.setCurrentIndex(window.work_index)
                self.assertEqual(window.surface_placement, chosen)
            finally:
                window.shutdown();window.close();window.deleteLater();self.app.processEvents()
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            pet.panel.settings = settings
            window = ChatWindow(pet)
            self.wait_image(window)
            try:
                window.tabs.setCurrentIndex(window.work_index)
                self.assertEqual(window.surface_placement, chosen)
                QTimer.singleShot(0, lambda: finish_dialog(False))
                window.adjust_background_position()
                self.assertEqual(window.surface_placement, chosen)
                self.assertEqual(settings.value('chat/background_placements'), {'work': chosen.as_dict()})
                source = root / 'replacement.png';self.make_image(source)
                with patch('deskpet.ui.background_controls.QFileDialog.getOpenFileName', return_value=(str(source), '')):
                    window.choose_background()
                self.wait_image(window)
                self.assertEqual(window.surface_placement, BackgroundPlacement())
                self.assertTrue(window.background_position_button.isEnabled())
                window.clear_background()
                self.assertFalse(window.background_position_button.isEnabled())
                self.assertFalse(settings.contains('chat/background_placement'))
                self.assertFalse(settings.contains('chat/background_placements'))
                self.assertTrue(window.surface_image.isNull())
            finally:
                window.shutdown();window.close()

    def test_page_crops_are_independent_preserve_legacy_and_survive_restart(self):
        from PySide6.QtWidgets import QPushButton
        from deskpet.ui.background_controls import PageBackgrounds
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);image = root / 'background.png';self.make_image(image)
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            legacy = BackgroundPlacement(30, 65, 140)
            settings.setValue('chat/background_placement', legacy.as_dict())
            surface = BackgroundSurface()
            manager = PageBackgrounds(surface, settings, image, 'chat/background', QPushButton(surface))
            manager.activate('work', '工作')
            self.assertEqual(surface.surface_placement, legacy)
            manager.save_position('work', BackgroundPlacement(80, 10, 200))
            manager.activate('companion', '陪伴')
            self.assertEqual(surface.surface_placement, legacy)
            manager.save_position('companion', BackgroundPlacement(10, 90, 110))
            manager.activate('work', '工作')
            self.assertEqual(surface.surface_placement, BackgroundPlacement(80, 10, 200))
            surface.close()
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            restored = BackgroundSurface()
            manager = PageBackgrounds(restored, settings, image, 'chat/background', QPushButton(restored))
            manager.activate('companion', '陪伴')
            self.assertEqual(restored.surface_placement, BackgroundPlacement(10, 90, 110))
            manager.activate('work', '工作')
            self.assertEqual(restored.surface_placement, BackgroundPlacement(80, 10, 200))
            restored.close()

    def test_programmatic_page_change_during_preview_saves_only_original_page(self):
        from PySide6.QtWidgets import QPushButton
        from deskpet.ui.background_controls import PageBackgrounds
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);image = root / 'background.png';self.make_image(image)
            settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            surface = BackgroundSurface()
            manager = PageBackgrounds(surface, settings, image, 'music/background', QPushButton(surface))
            self.wait_image(surface)
            manager.activate('tools.netease.account', '我的歌单')
            selected = BackgroundPlacement(10, 30, 190)
            def finish():
                dialog = next(c for c in surface.children() if isinstance(c, BackgroundPositionDialog))
                dialog.set_controls(selected)
                manager.activate('tools.netease.songs', '歌曲与歌单')
                dialog.accept()
            QTimer.singleShot(0, finish)
            manager.adjust()
            self.assertEqual(manager.position('tools.netease.account'), selected)
            self.assertEqual(surface.surface_placement, BackgroundPlacement())
            self.assertEqual(manager.records(), {'tools.netease.account': selected.as_dict()})
            surface.close()
