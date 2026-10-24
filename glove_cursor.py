"""Original raster hand art for widget-local cursors and foreground petting.

No vector substitute or downloaded meme hand is used by the runtime.
"""
from functools import lru_cache
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap

ART_ROOT = Path(__file__).resolve().parent / 'assets' / 'ui' / 'headpat'
HAND_CANVAS_WIDTH = 881
HAND_CANVAS_HEIGHT = 613
HAND_CONTACT_ANCHOR = QPointF(563, 461)
GLOVE_SIZE = 56
GLOVE_HOTSPOT = QPoint(round(563*GLOVE_SIZE/881), round(461*round(GLOVE_SIZE*613/881)/613))


def _unit(value, low, high):
    value = float(value)
    return max(low, min(high, value)) if math.isfinite(value) else 0.0


@lru_cache(maxsize=2)
def _source(state):
    path = ART_ROOT / f'hand-{state}.png'
    pixmap = QPixmap(str(path))
    if pixmap.isNull() or (pixmap.width(), pixmap.height()) != (HAND_CANVAS_WIDTH, HAND_CANVAS_HEIGHT):
        raise ValueError('摸头手掌素材缺失或尺寸不正确：' + path.name)
    return pixmap


def hand_contact_anchor(width=112):
    width = max(1, min(2048, int(width)))
    height = max(1, round(width*HAND_CANVAS_HEIGHT/HAND_CANVAS_WIDTH))
    return QPointF(HAND_CONTACT_ANCHOR.x()*width/HAND_CANVAS_WIDTH,
                   HAND_CONTACT_ANCHOR.y()*height/HAND_CANVAS_HEIGHT)


def _render_hand(state, width, contact, direction):
    """One aligned authored pose, gently tilted about the palm's contact edge.

    Callers cache quantized results. There is no timer or automatic movement;
    direction comes from mouse travel and pressure from actual contact.
    """
    width = max(1, min(2048, int(width)))
    height = max(1, round(width*HAND_CANVAS_HEIGHT/HAND_CANVAS_WIDTH))
    contact, direction = _unit(contact, 0, 1), _unit(direction, -1, 1)
    image = _source(state)
    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    anchor = hand_contact_anchor(width)
    painter.translate(anchor)
    painter.rotate(direction*2.5)
    painter.scale(1, 1-contact*.015)
    painter.translate(-anchor)
    painter.scale(width/HAND_CANVAS_WIDTH, height/HAND_CANVAS_HEIGHT)
    painter.drawPixmap(0, 0, image)
    painter.end()
    return canvas


def hand_pixmap(width=112, *, contact=0.0, direction=0.0):
    # Use one painted outline throughout contact/release. Blending or swapping
    # the two authored silhouettes would give the fingers a double outline.
    return _render_hand('contact', width, contact, direction)


def glove_pixmap(*, contact=0.0, direction=0.0):
    return _render_hand('hover', GLOVE_SIZE, contact, direction)


def make_glove_cursor(*, contact=0.0, direction=0.0):
    return QCursor(glove_pixmap(contact=contact, direction=direction),
                   GLOVE_HOTSPOT.x(), GLOVE_HOTSPOT.y())
