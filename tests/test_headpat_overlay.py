"""Foreground hand compositing checks; these do not simulate desktop input."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget
from desktop_pet import DesktopPet


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def state(self):
        return SimpleNamespace(petting=True, glove_contact=False,
            glove_overlay_alpha=0.0, glove_overlay_position=None, glove_hand_cache={},
            head_region=QRegion(QRect(70, 10, 120, 110)), hit_region=QRegion(QRect(50, 10, 160, 280)),
            active_petting=SimpleNamespace(previous=(120, 50), strength=.85, direction=.5), scale=1)

    def test_hand_tracks_smoothly_then_lifts_and_fades(self):
        state = self.state()
        DesktopPet.update_petting_hand(state, QPointF(100, 60), .1, True)
        self.assertTrue(state.glove_contact)
        self.assertGreater(state.glove_overlay_alpha, .7)
        start = state.glove_overlay_position.x()
        DesktopPet.update_petting_hand(state, QPointF(160, 60), .01, True)
        self.assertGreater(state.glove_overlay_position.x(), start)
        self.assertLess(state.glove_overlay_position.x(), 145)
        for _ in range(6):
            DesktopPet.update_petting_hand(state, QPointF(260, 200), .1, False)
        self.assertEqual(state.glove_overlay_alpha, 0)
        self.assertIsNone(state.glove_overlay_position)

    def test_contact_doubles_horizontal_offsets_without_changing_height(self):
        state = self.state()
        original = state.head_region.intersected(state.hit_region)
        expanded = DesktopPet.petting_contact_region(state)
        self.assertEqual(expanded.boundingRect(), QRect(10, 10, 240, 110))
        self.assertEqual(state.head_region, original)
        for point in (QPoint(15, 60), QPoint(245, 60)):
            self.assertFalse(original.contains(point))
            self.assertTrue(expanded.contains(point))
        for point in (QPoint(9, 60), QPoint(250, 60), QPoint(130, 9), QPoint(130, 120)):
            self.assertFalse(expanded.contains(point))

    def test_expanded_margin_receives_input_only_during_petting(self):
        state = self.state()
        state.petting_contact_region = lambda: DesktopPet.petting_contact_region(state)
        state.rect = lambda: QRect(0, 0, 260, 310)
        for enabled in (True, False):
            state.petting = enabled
            canvas = QPixmap(260, 310)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            try:
                DesktopPet.paint_petting_contact_region(state, painter)
            finally:
                painter.end()
            image = canvas.toImage()
            self.assertEqual(image.pixelColor(15, 60).alpha(), 1 if enabled else 0)
            self.assertEqual(image.pixelColor(245, 60).alpha(), 1 if enabled else 0)
            self.assertEqual(image.pixelColor(130, 120).alpha(), 0)

    def test_compositing_keeps_original_hit_regions_and_reuses_art(self):
        state = self.state()
        state.glove_overlay_alpha = 1
        state.glove_overlay_position = QPointF(130, 55)
        head, hit = QRegion(state.head_region), QRegion(state.hit_region)
        canvas = QPixmap(260, 310)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        try:
            DesktopPet.paint_petting_hand(state, painter)
            cache = dict(state.glove_hand_cache)
            DesktopPet.paint_petting_hand(state, painter)
            self.assertEqual(cache.keys(), state.glove_hand_cache.keys())
            self.assertEqual(state.head_region, head)
            self.assertEqual(state.hit_region, hit)
        finally:
            painter.end()
        image = canvas.toImage()
        self.assertTrue(all(image.pixelColor(x, 0).alpha() == 0 for x in range(image.width())),
                        'the cuff must not be cropped by the top window edge')
        self.assertGreater(image.pixelColor(130, 50).alpha(), 0)

    def test_native_cursor_is_hidden_only_on_effective_contact(self):
        widget = QWidget()
        widget.petting = True
        widget.glove_contact = True
        widget.glove_cursor_pose = None
        widget.glove_cursor_cache = {}
        DesktopPet.update_petting_cursor(widget, .8, .5)
        self.assertEqual(widget.cursor().shape(), Qt.CursorShape.BlankCursor)
        widget.glove_contact = False
        DesktopPet.update_petting_cursor(widget, .8, .5)
        self.assertEqual(widget.cursor().shape(), Qt.CursorShape.BitmapCursor)
        widget.close()

    def test_missing_authored_art_is_reported_before_starting_animation(self):
        messages, exits = [], []
        state = SimpleNamespace(live2d_renderer=object(), mouse_passthrough=False,
            stop_walk=lambda: None,
            dragging=False, sleeping=False, using_phone=False,
            toolbar=SimpleNamespace(hide=lambda: None),
            behavior=SimpleNamespace(has_action=lambda _: False),
            bubble=SimpleNamespace(say=messages.append),
            end_petting=lambda: exits.append(True), glove_cursor_cache={})
        with patch('glove_cursor.hand_pixmap', side_effect=ValueError('missing')):
            DesktopPet.start_petting(state)
        self.assertEqual(exits, [True])
        self.assertIn('素材', messages[0])


if __name__ == '__main__':
    unittest.main()
