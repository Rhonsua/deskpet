"""Small, asset-free pastel smoke puffs and confetti drawn IN FRONT of the pet."""
import math
from functools import lru_cache
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen


@lru_cache(maxsize=12)
def cloud_image(width, height, bx, by, bw, bh):
    image = QImage(width*2, height*2, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(2)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # A united opaque silhouette hides hair, hands and feet; no translucent
    # overlapping circles through which the character would still show.
    box = QRectF(bx, by, bw, bh)
    cx, cy = box.center().x(), box.center().y()
    cloud = QPainterPath()
    radius = box.width() / 2
    cloud.addEllipse(QPointF(cx, cy), radius*.88, radius*.88)
    puffs = []
    for i in range(14):
        angle = i * math.tau / 14
        x = cx + math.cos(angle) * radius * .78
        y = cy + math.sin(angle) * radius * .78
        rx = radius * (.20 + .025 * math.sin(i*2.3))
        ry = rx
        puff = QRectF(x-rx, y-ry, 2*rx, 2*ry)
        part = QPainterPath()
        part.addEllipse(puff)
        cloud = cloud.united(part)
        puffs.append(puff)
    painter.setPen(QPen(QColor('#a8d6e4'), 1.4))
    painter.setBrush(QColor('#f0faff'))
    painter.drawPath(cloud)
    painter.setPen(Qt.PenStyle.NoPen)
    for i, puff in enumerate(puffs):
        painter.setBrush(QColor('#e0f2fc' if i % 3 else '#eee9ff'))
        painter.drawEllipse(puff.adjusted(4, 4, -4, -4))
    # Soft central puffs avoid a flat rectangle while keeping the cover opaque.
    painter.setBrush(QColor('#f6fcff'))
    for i in range(5):
        angle = i*math.tau/5
        painter.drawEllipse(QPointF(cx + math.cos(angle)*radius*.32,
                                    cy + math.sin(angle)*radius*.32), radius*.48, radius*.48)
    painter.end()
    return image


def draw_teleport(painter, canvas, body, visual):
    if visual.smoke <= 0:
        return
    # The foreground window is square and larger than the narrow pet canvas.
    diameter = min(canvas.width(), canvas.height()) - 20
    box = QRectF(canvas.center().x()-diameter/2, canvas.center().y()-diameter/2,
                 diameter, diameter)
    cx, cy = box.center().x(), box.center().y()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(visual.smoke)
    spread = .12 + .88 * visual.bloom
    painter.translate(cx, cy)
    painter.scale(spread, spread)
    painter.translate(-cx, -cy)
    # Fade the completed cloud once, so overlapping puffs do not leave ghosts.
    painter.drawImage(QPointF(0, 0), cloud_image(round(canvas.width()), round(canvas.height()),
                                               box.x(), box.y(), box.width(), box.height()))
    painter.restore()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setOpacity(visual.smoke)
    palette = ('#72cee9', '#f3a9c6', '#f6d679', '#afa5eb', '#87d9bb')
    for i in range(22):
        angle = i * 2.39996
        travel = .40 + .55 * visual.burst
        x = cx + math.cos(angle) * box.width() * travel
        y = cy + math.sin(angle) * box.height() * travel * .62 + visual.burst**2 * 24
        painter.save()
        painter.translate(x, y)
        painter.rotate(i*37 + visual.burst*180)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette[i % len(palette)]))
        painter.drawRoundedRect(QRectF(-2, -4, 4, 8), 1, 1)
        painter.restore()
    painter.restore()
