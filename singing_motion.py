"""Three directional singing poses with independent, continuous leg deformation."""
import math
from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QPolygonF, QRegion, QTransform


def singing_pose(seconds):
    yaw = math.sin(seconds * math.tau / 4.8)
    if yaw < -0.45:
        return 'sing-left', yaw + 0.7
    if yaw > 0.45:
        return 'sing-right', yaw - 0.7
    return 'sing-front', yaw


def leg_offset(seconds, fraction, side, scale):
    phase = seconds * 5 + side * math.pi
    weight = fraction * fraction * (3 - 2 * fraction)
    return (math.sin(phase) * 3.2 * scale * weight,
            -max(0, math.sin(phase)) * 2.4 * scale * weight)


class SingingRig:
    def __init__(self, pixmap, mask):
        self.pixmap = pixmap
        self.mask = mask
        self.hem = round(pixmap.height() * 0.64)
        self.upper = QRect(0, 0, pixmap.width(), self.hem)
        self.upper_mask = mask.intersected(QRegion(self.upper))
        self.bands = []
        middle = pixmap.width() // 2
        image = pixmap.toImage()
        for y in range(self.hem, pixmap.height(), 4):
            height = min(4, pixmap.height() - y)
            runs, start = [], None
            for x in range(pixmap.width() + 1):
                solid = x < pixmap.width() and any(image.pixelColor(x, row).alpha() >= 128
                                                  for row in range(y, y + height))
                if solid and start is None:
                    start = x
                elif not solid and start is not None:
                    if x - start >= 3:
                        runs.append((start, x))
                    start = None
            gaps = [(a[1] + b[0]) // 2 for a, b in zip(runs, runs[1:])]
            if gaps:
                middle = min(gaps, key=lambda x: abs(x - middle))
            for side, (x, width) in enumerate(((0, middle), (middle, pixmap.width() - middle))):
                rect = QRect(x, y, width, min(4, pixmap.height() - y))
                self.bands.append((side, rect, mask.intersected(QRegion(rect))))

    def draw(self, painter, seconds, scale):
        painter.drawPixmap(QPoint(0, 0), self.pixmap, self.upper)
        result = QRegion(self.upper_mask)
        span = max(1, self.pixmap.height() - self.hem)
        for side, rect, mask in self.bands:
            top, bottom = rect.y(), rect.y() + rect.height()
            dx1, dy1 = leg_offset(seconds, (top - self.hem) / span, side, scale)
            dx2, dy2 = leg_offset(seconds, (bottom - self.hem) / span, side, scale)
            left, right = rect.x(), rect.x() + rect.width()
            source = QPolygonF([QPointF(left, top), QPointF(right, top),
                                QPointF(right, bottom), QPointF(left, bottom)])
            target = QPolygonF([QPointF(left + dx1, top + dy1), QPointF(right + dx1, top + dy1),
                                QPointF(right + dx2, bottom + dy2), QPointF(left + dx2, bottom + dy2)])
            warp = QTransform()
            if not QTransform.quadToQuad(source, target, warp):
                continue
            painter.save()
            painter.setTransform(warp, True)
            painter.setClipRect(rect)
            painter.drawPixmap(0, 0, self.pixmap)
            painter.restore()
            result = result.united(warp.map(mask))
        return result
