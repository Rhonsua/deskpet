"""Sprite fitting helpers shared by desktop and tool windows."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPixmap, QImage

_SOLID_ALPHA = bytes(1 if value >= 160 else 0 for value in range(256))


def sprite_bounds(pixmap):
    """Ignore isolated alpha specks when fitting a sprite into its display area."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_Alpha8)
    width, height = image.width(), image.height()
    if not width or not height:
        return pixmap.rect()
    pixels = bytes(image.constBits()).translate(_SOLID_ALPHA)
    stride = image.bytesPerLine()
    # Qt extracts alpha natively; bytes translation, slicing and sum avoid a
    # Python call/lookup for every RGBA pixel while preserving the speck filter.
    rows = [y for y in range(height)
            if sum(pixels[y * stride:y * stride + width]) >= max(4, width // 100)]
    xs = [x for x in range(width)
          if sum(pixels[x:height * stride:stride]) >= max(4, height // 100)]
    if rows and xs:
        return QRect(xs[0], rows[0], xs[-1] - xs[0] + 1, rows[-1] - rows[0] + 1)
    return pixmap.rect()



def update_cover(panel, filename, fitted=None):
    pixmap = fitted if fitted is not None else QPixmap(str(filename))
    if not pixmap.isNull():
        if fitted is None:
            bounds = sprite_bounds(pixmap)
            if not bounds.isEmpty():
                pixmap = pixmap.copy(bounds)
        panel.cover.setPixmap(pixmap.scaled(72, 84, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
