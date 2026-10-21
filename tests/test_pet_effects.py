import unittest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter
from pet_effects import draw_effects


class PetEffectsTests(unittest.TestCase):
    def test_each_supported_action_has_transparent_sparse_vector_effects(self):
        for activity in ('idle', 'sing', 'turn', 'head_rub', 'mouse_wave', 'sleep',
                         'phone', 'eat', 'lift', 'land', 'happy', 'level_up'):
            image = QImage(260, 310, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            draw_effects(painter, QSize(260, 310), 1, activity, .3, 1)
            painter.end()
            alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
            values = bytes(alpha.bits())
            with self.subTest(activity=activity):
                self.assertGreater(max(values), 0)
                self.assertLess(max(values), 180)
                self.assertLess(sum(value > 0 for value in values), len(values)*.3)


if __name__ == '__main__':
    unittest.main()
