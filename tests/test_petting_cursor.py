"""Runtime cursor lifecycle without a renderer, audio worker, or real input."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from desktop_pet import DesktopPet
from glove_cursor import GLOVE_HOTSPOT, make_glove_cursor
from mouse_interactions import ActiveHeadPetting, MouseInteractions


class CursorSubject(QWidget):
    start_petting = DesktopPet.start_petting
    end_petting = DesktopPet.end_petting
    update_petting_cursor = DesktopPet.update_petting_cursor

    def __init__(self):
        super().__init__()
        self.live2d_renderer = object()
        self.mouse_passthrough = self.dragging = False
        self.sleeping = self.using_phone = self.petting = False
        self.glove_cursor = self.glove_cursor_pose = None
        self.glove_cursor_cache = {}
        self.glove_contact = False
        self.glove_overlay_alpha = 0.0
        self.glove_overlay_position = None
        self.active_petting = ActiveHeadPetting()
        self.mouse_interactions = MouseInteractions()
        self.toolbar = Mock()
        self.behavior = Mock()
        self.behavior.has_action.return_value = False
        self.click_timer = Mock()
        self.hold_timer = Mock()
        self.bubble = Mock()
        self.reveal_dock = Mock()


class PettingCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pet = CursorSubject()
        self.addCleanup(self.pet.close)

    def test_clicking_head_or_body_does_not_enter_petting(self):
        self.pet.react = Mock()
        self.pet.pat = Mock()
        for head in (True, False):
            self.pet.touch_head = head
            DesktopPet.touch(self.pet)
            self.assertFalse(self.pet.petting)
        self.pet.pat.assert_not_called()
        self.assertEqual(self.pet.react.call_count, 2)

    def test_start_uses_neutral_cursor_and_contact_hides_duplicate_hand(self):
        # A previous gesture may still be fading when the mode is re-entered.
        self.pet.active_petting.strength = 0.8
        self.pet.active_petting.direction = -0.9
        self.pet.start_petting()
        self.assertEqual(self.pet.glove_cursor_pose, (0, 0))
        words = self.pet.bubble.say.call_args.args[0]
        self.assertNotIn('手套', words)
        self.assertNotIn('退出', words)
        neutral = self.pet.cursor().pixmap().toImage()
        self.pet.glove_contact = True
        self.pet.update_petting_cursor(0.8, -0.9)
        self.assertEqual(self.pet.glove_cursor_pose, 'overlay')
        self.assertEqual(self.pet.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.pet.glove_contact = False
        self.pet.update_petting_cursor(0, 1)
        self.assertEqual(self.pet.glove_cursor_pose, (0, 0))
        self.assertEqual(self.pet.cursor().pixmap().toImage(), neutral)
        self.assertEqual(self.pet.cursor().hotSpot(), GLOVE_HOTSPOT)

    def test_quantized_cache_is_bounded_and_never_repaints_cached_poses(self):
        with patch('glove_cursor.make_glove_cursor', wraps=make_glove_cursor) as build:
            self.pet.start_petting()
            for _ in range(3):
                for contact in (0, .25, .5, .75, 1):
                    for direction in (-1, -2/3, -1/3, 0, 1/3, 2/3, 1):
                        self.pet.update_petting_cursor(contact, direction)
            # Pressure/direction animate the foreground palm, not this cue.
            self.assertEqual(len(self.pet.glove_cursor_cache), 1)
            self.assertEqual(build.call_count, 1)
            with patch.object(self.pet, 'setCursor', wraps=self.pet.setCursor) as apply:
                for _ in range(100):
                    self.pet.update_petting_cursor(1, .99)
                apply.assert_not_called()

    def test_exit_restores_normal_cursor_and_disables_late_updates(self):
        self.pet.start_petting()
        self.pet.glove_contact = True
        self.pet.glove_overlay_alpha = 1.0
        self.pet.update_petting_cursor(1, -1)
        self.assertEqual(self.pet.cursor().shape(), Qt.CursorShape.BlankCursor)
        self.pet.end_petting()
        self.assertEqual(self.pet.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.assertEqual(self.pet.glove_overlay_alpha, 0)
        self.assertFalse(self.pet.glove_contact)
        self.assertIsNone(self.pet.glove_cursor_pose)
        self.assertIsNone(self.pet.glove_cursor)
        self.pet.update_petting_cursor(1, 1)
        self.assertEqual(self.pet.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.pet.start_petting()
        self.assertEqual(self.pet.glove_cursor_pose, (0, 0))
        self.assertEqual(self.pet.cursor().shape(), Qt.CursorShape.BitmapCursor)
        self.assertIsNone(QApplication.overrideCursor())


if __name__ == '__main__':
    unittest.main()
