"""Small cached shop illustrations shared by the catalogue and the pet painter."""
from functools import lru_cache
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from deskpet.pet.catalog import ITEMS


@lru_cache(maxsize=20)
def item_pixmap(key):
    return QPixmap(str(ITEMS[key].image))


@lru_cache(maxsize=48)
def _background_size(key, width):
    return item_pixmap(key).scaledToWidth(width, Qt.SmoothTransformation)


def draw_background(painter, key, size, scale, seconds, reveal=1.):
    if not key or reveal <= 0 or ITEMS[key].panoramic:
        return
    painter.save()
    painter.setOpacity(painter.opacity() * reveal)
    if ITEMS[key].animated:
        painter.drawPixmap(0, 0, scene_frame(key, size.width(), size.height(), int(seconds * SCENE_FPS)))
    else:
        width = size.width()
        span = min(width - 4, round(width * (.70 if key == 'picnic' else .94)))
        image = _background_size(key, max(1, span))
        painter.drawPixmap((width - image.width()) // 2, round(296 * scale) - image.height(), image)
    painter.restore()


def draw_accessory(painter, key, head):
    """Called in pose coordinates, with the character's current transform still active."""
    if not key or head.isEmpty():
        return
    pixmap = item_pixmap(key)
    if pixmap.isNull():
        return
    width = head.width() * .32
    height = width * pixmap.height() / pixmap.width()
    center_x = head.left() + head.width() * .76
    center_y = head.top() + head.height() * .35
    target = QRectF(center_x - width / 2, center_y - height / 2, width, height)
    painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))


SCENE_FPS = 30
SCENE_LOOP_SECONDS = 12


@lru_cache(maxsize=6)
def _scene_backplate(key, width, height):
    source = item_pixmap(key)
    size = source.size().scaled(QSize(width, height), Qt.KeepAspectRatioByExpanding)
    bounds = QRectF((width - size.width()) // 2, (height - size.height()) // 2,
                    size.width(), size.height())
    plate = QPixmap(width, height)
    plate.fill(Qt.transparent)
    p = QPainter(plate)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, width, height), 9, 9)
    p.setClipPath(clip)
    p.drawPixmap(bounds, source, QRectF(source.rect()))
    p.end()
    return plate, bounds, clip


def _clouds(p, phase):
    for i, (anchor, y, radius) in enumerate(((24, 22, 5), (68, 37, 3.5), (82, 11, 3))):
        x = anchor + 6 * math.sin(math.tau * phase + i * 2)
        cloud = QPainterPath()
        for dx, dy, r in ((-1.25, .3, .75), (-.4, -.2, 1), (.65, 0, .88), (1.45, .4, .58)):
            cloud.addEllipse(QPointF(x + dx*radius, y + dy*radius), r*radius, r*radius*.77)
        cloud.setFillRule(Qt.WindingFill)
        p.fillPath(cloud, QColor(255, 255, 255, 187))
    p.save()
    p.translate(-12 + 124 * phase, 38 - 10 * math.sin(math.pi * phase) - 7 * phase)
    p.rotate(-12 + 12 * phase)
    p.setPen(QPen(QColor('#55778e'), .45, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor('#fff9d9'))
    p.drawPolygon(QPolygonF([QPointF(-5,-2), QPointF(4,-.9), QPointF(-2,2.9), QPointF(-2,.7)]))
    p.drawLine(QPointF(-2,.7), QPointF(4,-.9))
    p.restore()


def _pond(p, phase):
    cycle = math.tau * phase
    for i in range(12):
        angle = cycle + i * 2.39
        x = (i*31 % 93) + 3 + 2.8*math.sin(angle)
        y = 30 + (i*17 % 48) + 3.1*math.cos(cycle*2 + i*1.9)
        glow = .5 + .5 * math.sin(cycle*2 + i*2.39)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(210, 255, 129, round(18 + 45*glow)))
        p.drawEllipse(QPointF(x,y), 1.45+glow, 1.45+glow)
        p.setBrush(QColor(255, 250, 151, round(70+180*glow)))
        p.drawEllipse(QPointF(x,y), .5+.34*glow, .5+.34*glow)
    p.setBrush(Qt.NoBrush)
    for i, (x,y) in enumerate(((22,63), (68,59), (87,62))):
        ripple = (phase*3 + i/3) % 1
        p.setPen(QPen(QColor(169, 245, 231, round(110 * math.sin(math.pi*ripple)**2)), .38))
        p.drawEllipse(QPointF(x,y), 1+5*ripple, .2+1.2*ripple)


def _encore(p, phase):
    for i, (x, color) in enumerate(((13.5,(255,172,222)), (87,(140,240,255)))):
        center = 50 + 23*math.sin(math.tau*phase + i*math.pi)
        light = QLinearGradient(x,18.5,center,88)
        light.setColorAt(0,QColor(*color,150))
        light.setColorAt(1,QColor(*color,28))
        p.setPen(Qt.NoPen)
        p.setBrush(light)
        p.drawPolygon(QPolygonF([QPointF(x-1,18.5), QPointF(x+1,18.5),
                                 QPointF(center+12,90), QPointF(center-12,90)]))
        p.setBrush(QColor(*color,94))
        p.drawEllipse(QPointF(center,90),12,2.4)
    for i in range(6):
        rise=(phase*2 + i/6) % 1
        x=10 + (i*17 % 80) + 2.5*math.sin(rise*math.tau+i)
        y=80-rise*56
        ink=QColor(255,250,209,round(185*math.sin(math.pi*rise)**2))
        p.setPen(QPen(ink,.62,Qt.SolidLine,Qt.RoundCap))
        p.setBrush(ink)
        p.drawEllipse(QPointF(x,y),1.1,.78)
        p.drawLine(QPointF(x+1,y), QPointF(x+1,y-4))
        p.drawLine(QPointF(x+1,y-4), QPointF(x+2.7,y-3.2))


_SCENE_MOTION = {'cloudsky': _clouds, 'fireflies': _pond, 'encore': _encore}


@lru_cache(maxsize=4)
def scene_frame(key, width, height, frame):
    """Paint only moving elements over the same registered camera crop."""
    cycle = SCENE_LOOP_SECONDS * SCENE_FPS
    phase = (frame % cycle) / cycle
    plate, bounds, clip = _scene_backplate(key, width, height)
    scene = QPixmap(plate)
    p = QPainter(scene)
    p.setRenderHint(QPainter.Antialiasing)
    p.setClipPath(clip)
    p.translate(bounds.topLeft())
    p.scale(bounds.width()/100, bounds.height()/100)
    _SCENE_MOTION[key](p, phase)
    p.end()
    return scene
