"""Sprite fitting helpers shared by desktop and tool windows."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPixmap, QImage


def sprite_bounds(pixmap):
    """Ignore isolated alpha specks when fitting a sprite into its display area."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    pixels = image.constBits()
    stride = image.bytesPerLine()
    rows, columns = [], [0] * width
    for y in range(height):
        count = 0
        for x in range(width):
            if pixels[y * stride + x * 4 + 3] >= 160:
                count += 1
                columns[x] += 1
        if count >= max(4, width // 100):
            rows.append(y)
    xs = [x for x, count in enumerate(columns) if count >= max(4, height // 100)]
    if rows and xs:
        return QRect(xs[0], rows[0], xs[-1] - xs[0] + 1, rows[-1] - rows[0] + 1)
    return pixmap.rect()



def update_cover(panel, filename):
    pixmap = QPixmap(str(filename))
    if not pixmap.isNull():
        bounds = sprite_bounds(pixmap)
        if not bounds.isEmpty():
            pixmap = pixmap.copy(bounds)
        panel.cover.setPixmap(pixmap.scaled(72, 84, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
