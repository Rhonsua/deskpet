import random
import unittest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from visual_style import sprite_bounds


class ImageSprite:
    def __init__(self, image):
        self.image = image

    def toImage(self):
        return self.image

    def rect(self):
        return self.image.rect()


def reference_bounds(image):
    width, height = image.width(), image.height()
    rows, columns = [], [0] * width
    for y in range(height):
        count = 0
        for x in range(width):
            if image.pixelColor(x, y).alpha() >= 160:
                count += 1
                columns[x] += 1
        if count >= max(4, width // 100):
            rows.append(y)
    xs = [x for x, count in enumerate(columns) if count >= max(4, height // 100)]
    if rows and xs:
        return QRect(xs[0], rows[0], xs[-1]-xs[0]+1, rows[-1]-rows[0]+1)
    return image.rect()


class SpriteBoundsTests(unittest.TestCase):
    def test_same_speck_filter_with_thresholds_and_stride_padding(self):
        randomizer = random.Random(42)
        for width, height in ((33, 27), (64, 29), (13, 41)):
            image = QImage(width, height, QImage.Format.Format_RGBA8888)
            image.fill(0)
            for y in range(4, height-5):
                for x in range(3, width-4):
                    image.setPixelColor(x, y, QColor(20, 50, 90, randomizer.choice((0, 159, 160, 255))))
            image.setPixelColor(0, 0, QColor(0, 0, 0, 255))
            self.assertEqual(sprite_bounds(ImageSprite(image)), reference_bounds(image))

    def test_empty_and_opaque_images_keep_original_bounds(self):
        self.assertEqual(sprite_bounds(ImageSprite(QImage())), QRect())
        for format in (QImage.Format.Format_RGBA8888, QImage.Format.Format_RGB32):
            image = QImage(17, 23, format)
            image.fill(0)
            self.assertEqual(sprite_bounds(ImageSprite(image)), reference_bounds(image))
