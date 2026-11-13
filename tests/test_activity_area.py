"""Range persistence, real selector input, and movement integration without user data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, QRect, QSize, QSettings, Qt
from PySide6.QtGui import QImage, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from deskpet.animation.activity_area import (
    AREA_KEY, ActivityAreaRuntime, read_area, roaming_bounds, roaming_allowed,
)
from deskpet.animation.teleport_runtime import TeleportRuntime
from deskpet.ui.activity_area_picker import ActivityAreaPicker, AreaOverlay
from tests.test_companion_actions import WalkingPet


class RangePet(ActivityAreaRuntime, TeleportRuntime, WalkingPet):
    def __init__(self):
        super().__init__()
        self.panel.settings = NS(value=lambda key, default=None, **kw: default,
                                 setValue=Mock(), sync=Mock(), remove=Mock())
        self.init_activity_area()
        self.init_teleport()
        self.vertical = 20
        self.extent = QSize(100, 200)
        self.physical = QRect(0, 0, 1000, 600)
        self.fold_timer = NS(stop=Mock())
        self.effects = NS(sync=Mock())
        self.hit_region = QRegion(QRect(0, 0, 100, 200))
        self.bubble.say = Mock()
        self.live2d_renderer = NS(crawl_available=True)

    def width(self): return self.extent.width()
    def height(self): return self.extent.height()
    def y(self): return self.vertical
    def screen_bounds(self): return self.physical
    def pos(self): return QPoint(self.x(), self.y())
    def size(self): return self.extent
    def move(self, point, y=None):
        point = QPoint(point, y) if y is not None else point
        self.position, self.vertical = point.x(), point.y()


class ActivityAreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_persistence_round_trip_and_invalid_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.ini')
            settings = QSettings(path, QSettings.Format.IniFormat)
            area = QRect(-1280, 90, 750, 650)
            settings.setValue(AREA_KEY, area)
            settings.sync()
            self.assertEqual(read_area(QSettings(path, QSettings.Format.IniFormat)), area)
            for invalid in ('bad', QRect(), QRect(10, 10, -20, 200)):
                settings.setValue(AREA_KEY, invalid)
                self.assertIsNone(read_area(settings))

    def test_apply_repositions_once_preserves_mode_and_clear_preserves_toggles(self):
        pet = RangePet()
        pet.behavior.set_mode('sleep')
        pet.dock_edge = 'left'
        area = QRect(400, 200, 400, 350)
        with patch('deskpet.animation.activity_area.QApplication.screens',
                   return_value=[NS(availableGeometry=lambda: pet.physical)]):
            self.assertTrue(pet.apply_activity_area(area))
            self.assertEqual(pet.pos(), QPoint(400, 200))
            self.assertEqual(pet.behavior.mode, 'sleep')
            self.assertEqual(pet.dock_edge, '')
            pet.move(QPoint(30, 20))
            self.assertFalse(roaming_allowed(pet, roaming_bounds(pet)))
            self.assertEqual(pet.pos(), QPoint(30, 20))
            self.assertFalse(pet.apply_activity_area(QRect(0, 0, 90, 190)))
            self.assertFalse(pet.apply_activity_area(QRect(900, 0, 500, 500)))
            self.assertEqual(pet.activity_area, area)
        before = (pet.auto_walk_enabled, pet.auto_teleport_enabled)
        pet.clear_activity_area()
        self.assertIsNone(pet.activity_area)
        self.assertEqual((pet.auto_walk_enabled, pet.auto_teleport_enabled), before)
        self.assertEqual(pet.pos(), QPoint(30, 20))
        pet.panel.settings.remove.assert_called_once_with(AREA_KEY)

    def test_negative_monitor_disconnection_and_size_changes_pause_without_jump(self):
        pet = RangePet()
        pet.physical = QRect(-1200, -200, 1200, 800)
        pet.activity_area = QRect(-1000, -100, 700, 600)
        pet.move(QPoint(-900, 0))
        self.assertTrue(roaming_allowed(pet, roaming_bounds(pet)))
        pet.extent = QSize(800, 200)
        self.assertFalse(roaming_allowed(pet, roaming_bounds(pet)))
        pet.extent = QSize(100, 200)
        pet.physical = QRect(0, 0, 1000, 600)
        self.assertTrue(roaming_bounds(pet).isEmpty())
        self.assertFalse(pet.start_walk(direction=1, chat_command=True))
        self.assertFalse(pet._start_teleport(automatic=False))
        self.assertEqual(pet.pos(), QPoint(-900, 0))

    def test_left_right_and_crawl_routes_never_leave_box(self):
        for direction, crawl in ((1, False), (-1, False), (-1, True)):
            pet = RangePet()
            pet.activity_area = QRect(140, 0, 320, 300)
            with patch('deskpet.animation.walk_runtime.random.random', return_value=0 if crawl else 1):
                self.assertTrue(pet.start_walk(direction=direction, cycles=20, chat_command=True))
                self.assertEqual(pet.walk_controller.motion, 'crawl' if crawl else 'walk')
                for _ in range(500):
                    pet.tick_walk(.1)
                    self.assertTrue(pet.activity_area.contains(QRect(pet.pos(), pet.size())))
                self.assertFalse(pet.walk_controller.active)

    def test_drag_out_resize_and_screen_change_interrupt_active_movement(self):
        for change in ('drag', 'resize', 'screen'):
            pet = RangePet()
            pet.activity_area = QRect(100, 0, 600, 600)
            self.assertTrue(pet.start_walk(direction=1, chat_command=True))
            if change == 'drag':
                pet.move(QPoint(50, 0))
            elif change == 'resize':
                pet.extent = QSize(700, 200)
            else:
                pet.physical = QRect(1000, 0, 1000, 600)
            before = pet.pos()
            pet.tick_walk(.1)
            self.assertFalse(pet.walk_controller.active)
            self.assertEqual(pet.pos(), before)

    def test_teleport_targets_and_frame_positions_use_selected_bounds(self):
        for direction in (-1, 1):
            pet = RangePet()
            pet.activity_area = QRect(120, 0, 500, 600)
            pet.move(QPoint(200, 200))
            self.assertTrue(pet._start_teleport(automatic=False, direction=direction))
            target = pet.teleport_controller.destination
            self.assertTrue(0 <= target <= 400)
            self.assertEqual(target > 200, direction > 0)
            for _ in range(30):
                pet.tick_teleport(.1)
                self.assertTrue(pet.activity_area.contains(QRect(pet.pos(), pet.size())))
            self.assertEqual(pet.y(), target)
        pet = RangePet()
        pet.activity_area = QRect(120, 0, 500, 600)
        self.assertTrue(pet._start_teleport(automatic=False, direction=1))
        pet.move(QPoint(50, 20))
        pet.tick_teleport(.1)
        self.assertFalse(pet.teleport_controller.active)
        self.assertEqual(pet.pos(), QPoint(50, 20))

    def test_selector_blocks_commands_and_cancel_keeps_old_area(self):
        pet = RangePet()
        pet.activity_area = QRect(100, 0, 600, 600)
        pet.activity_area_picker = object()
        self.assertFalse(pet.start_walk(direction=1, chat_command=True))
        self.assertFalse(pet._start_teleport(automatic=False))
        pet._activity_area_selected(None)
        self.assertEqual(pet.activity_area, QRect(100, 0, 600, 600))
        pet.panel.settings.setValue.assert_not_called()

    def test_real_selector_reverse_drag_small_selection_and_escape(self):
        parent = QWidget()
        picker = ActivityAreaPicker(parent, QSize(140, 240))
        overlay = AreaOverlay(picker, QRect(-800, 30, 800, 600))
        picker.overlays.append(overlay)
        results = []
        picker.finished.connect(results.append)
        overlay.show()
        self.app.processEvents()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        self.assertEqual(results, [])
        self.assertFalse(picker.done)
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(500, 450))
        QTest.mouseMove(overlay, QPoint(100, 100))
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(results, [QRect(-700, 130, 401, 351)])
        self.assertFalse(overlay.isVisible())
        for key in ('escape', 'right-click'):
            picker = ActivityAreaPicker(parent, QSize(140, 240))
            picker.open()
            cancelled = []
            picker.finished.connect(cancelled.append)
            overlay = picker.overlays[0]
            if key == 'escape':
                QTest.keyClick(overlay, Qt.Key.Key_Escape)
            else:
                QTest.mouseClick(overlay, Qt.MouseButton.RightButton)
            self.assertEqual(cancelled, [None])
            self.assertTrue(all(not w.isVisible() for w in picker.overlays))
        parent.close()

    def test_full_pet_settings_toolbar_and_selector_flow(self):
        from deskpet.app import Pet
        from deskpet.ui.appearance import APPEARANCE_REVISION
        from PySide6.QtWidgets import QPushButton
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'LOCALAPPDATA': folder}):
            root = Path(folder)
            character = root / 'characters/range-test'
            character.mkdir(parents=True)
            image = QImage(64, 96, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.cyan)
            image.save(str(character / 'idle.png'))
            (character / 'character.json').write_text(json.dumps({
                'version': 1, 'id': 'range-test', 'name': 'Range test',
                'states': {'idle': 'idle.png'},
            }), encoding='utf-8')
            settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
            settings.setValue('appearance_revision', APPEARANCE_REVISION)
            settings.setValue('character_selection', 'external:range-test')
            pet = Pet(data_dir=root / 'data', settings=settings,
                      startup=NS(supported=False, enabled=lambda: False),
                      characters_dir=root / 'characters')
            try:
                pet.timer.stop()
                pet.panel.progress_timer.stop()
                self.assertIsNone(pet.activity_area)
                self.assertFalse(pet.clear_activity_area_action.isEnabled())
                pet.toolbar.page('rest')
                buttons = pet.toolbar.findChildren(QPushButton)
                choose = next(b for b in buttons if b.text() == '框选活动范围')
                choose.click()
                picker = pet.activity_area_picker
                self.assertIsNotNone(picker)
                self.assertFalse(pet.toolbar.isVisible())
                overlay = picker.overlays[0]
                self.app.processEvents()
                QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
                end = QPoint(20 + pet.width() + 80, 20 + pet.height() + 80)
                QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=end)
                self.assertIsNone(pet.activity_area_picker)
                self.assertIsNotNone(pet.activity_area)
                self.assertTrue(pet.activity_area.contains(QRect(pet.pos(), pet.size())))
                self.assertEqual(read_area(settings), pet.activity_area)
                self.assertTrue(pet.panel.clear_activity_area_button.isEnabled())
                self.assertTrue(pet.clear_activity_area_action.isEnabled())
                self.assertIn(str(pet.activity_area.width()), pet.panel.activity_area_note.text())
                pet.select_activity_area()
                QTest.keyClick(pet.activity_area_picker.overlays[0], Qt.Key.Key_Escape)
                self.assertEqual(read_area(settings), pet.activity_area)
                pet.panel.clear_activity_area_button.click()
                self.assertIsNone(read_area(settings))
                self.assertIsNone(pet.activity_area)
            finally:
                if pet.activity_area_picker is not None:
                    pet.activity_area_picker.finish(None)
                for timer in (pet.timer, pet.fold_timer, pet.click_timer, pet.hold_timer,
                              pet.panel.progress_timer, pet.panel.bilibili.watchdog):
                    timer.stop()
                pet.panel.shutdown_audio()
                pet.tray.hide()
                pet.hide()
                pet.panel.hide()
                pet.panel.store.close()
                pet.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
