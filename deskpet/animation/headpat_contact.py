"""Forgiving head contact without holes in hair artwork or window-edge clipping."""
from functools import lru_cache

from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QPainterPath, QRegion


@lru_cache(maxsize=64)
def _region(x, y, width, height, scale, retaining):
    if width <= 0 or height <= 0:
        return QRegion()
    # A broad rounded rectangle doesn't pinch near the crown like an ellipse.
    dx = round(max(width * .70, 48 * scale))
    dy = round(max(height * .25, 20 * scale))
    if retaining:
        dx += round(max(width * .22, 20 * scale))
        dy += round(max(height * .18, 14 * scale))
    box = QRect(x, y, width, height).adjusted(-dx, -dy, dx, dy)
    path = QPainterPath()
    radius = min(18 * scale, box.height() / 5)
    path.addRoundedRect(QRectF(box), radius, radius)
    return QRegion(path.toFillPolygon().toPolygon())


def contact_region(head, scale=1.0, *, retaining=False):
    """Local logical coordinates; the outer band keeps an established stroke."""
    return QRegion(_region(head.x(), head.y(), head.width(), head.height(),
                           round(scale, 3), bool(retaining)))
