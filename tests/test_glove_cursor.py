import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from glove_cursor import (ART_ROOT, HAND_CANVAS_WIDTH, HAND_CANVAS_HEIGHT,
                          HAND_CONTACT_ANCHOR, GLOVE_HOTSPOT, GLOVE_SIZE,
                          glove_pixmap, make_glove_cursor, hand_pixmap, hand_contact_anchor)


class GloveCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def assert_transparent_border(self, image):
        for x in range(image.width()):
            self.assertEqual(image.pixelColor(x, 0).alpha(), 0)
            self.assertEqual(image.pixelColor(x, image.height()-1).alpha(), 0)
        for y in range(image.height()):
            self.assertEqual(image.pixelColor(0, y).alpha(), 0)
            self.assertEqual(image.pixelColor(image.width()-1, y).alpha(), 0)

    def test_original_manifest_matches_runtime_alignment(self):
        manifest = json.loads((ART_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['canvas_size'], [HAND_CANVAS_WIDTH, HAND_CANVAS_HEIGHT])
        self.assertEqual(manifest['shared_anchor'], [HAND_CONTACT_ANCHOR.x(), HAND_CONTACT_ANCHOR.y()])
        for frame in manifest['frames'].values():
            self.assertTrue((ART_ROOT/frame['file']).is_file())
            self.assertTrue(frame['original_crop_rgba_preserved_exactly'])

    def test_cursor_uses_original_hover_pose_and_local_anchor(self):
        image = glove_pixmap().toImage()
        self.assertEqual(image.width(), GLOVE_SIZE)
        self.assert_transparent_border(image)
        cursor = make_glove_cursor()
        self.assertEqual(cursor.hotSpot(), GLOVE_HOTSPOT)
        self.assertNotEqual(image, hand_pixmap(GLOVE_SIZE).toImage(), 'hover and contact must use their separate original poses')
        previous = QApplication.overrideCursor()
        make_glove_cursor()
        self.assertIs(QApplication.overrideCursor(), previous)

    def test_transform_keeps_anchor_and_transparent_edges(self):
        for width in (56, 90, 112, 160):
            anchor = hand_contact_anchor(width)
            for contact in (0, .5, 1):
                for direction in (-1, 0, 1):
                    with self.subTest(width=width, contact=contact, direction=direction):
                        image = hand_pixmap(width, contact=contact, direction=direction).toImage()
                        self.assertEqual(image.height(), round(width*HAND_CANVAS_HEIGHT/HAND_CANVAS_WIDTH))
                        self.assertAlmostEqual(anchor.x(), 563*width/881)
                        self.assertAlmostEqual(anchor.y(), 461*image.height()/613)
                        self.assert_transparent_border(image)

    def test_values_are_clamped_and_same_pose_has_no_timer(self):
        self.assertEqual(hand_pixmap(contact=3, direction=-4).toImage(),
                         hand_pixmap(contact=1, direction=-1).toImage())
        self.assertEqual(glove_pixmap(contact=float('nan'), direction=float('inf')).toImage(),
                         glove_pixmap().toImage())
        self.assertEqual(hand_pixmap(contact=.8, direction=.4).toImage(),
                         hand_pixmap(contact=.8, direction=.4).toImage())


if __name__ == '__main__':
    unittest.main()
