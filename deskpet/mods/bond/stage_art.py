"""Local watercolor stage scenery and lightweight performance lighting."""
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from .scrapbook import activity_images


SCENES = {'night':(0,0), 'ocean':(1,0), 'sakura':(0,1), 'gold':(1,1)}
STAGE_SCENES = ('night', 'night', 'ocean', 'night', 'sakura', 'gold')


def scene_name(theme, stage):
    return theme if theme in SCENES else STAGE_SCENES[max(0, min(5, stage))]


def stage_image(name):
    return activity_images().get(Path(__file__).with_name('assets') / (name + '.webp'))


def paint_stage(painter, rect, theme, stage):
    target = QRectF(rect)
    if target.isEmpty():
        return
    sheet = stage_image('stage-scenery')
    name = scene_name(theme, stage)
    if sheet.isNull():
        gradient = QLinearGradient(target.topLeft(), target.bottomRight())
        gradient.setColorAt(0, QColor('#172b47'))
        gradient.setColorAt(1, QColor({'night':'#425e89','ocean':'#358489','sakura':'#926586','gold':'#956549'}[name]))
        painter.fillRect(target, gradient)
        return
    col, row = SCENES[name]
    w, h = sheet.width()/2, sheet.height()/2
    # Inset each cell before filtering, so colors from its neighbor never bleed in at the edges.
    cell = QRectF(col*w+2, row*h+2, w-4, h-4)
    scale = max(target.width()/cell.width(), target.height()/cell.height())
    crop_w, crop_h = target.width()/scale, target.height()/scale
    source = QRectF(cell.center().x()-crop_w/2, cell.top()+(cell.height()-crop_h)*.64, crop_w, crop_h)
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawPixmap(target, sheet, source)
    if not theme and stage in (1, 3):
        painter.fillRect(target, QColor(99, 70, 135, 30) if stage == 1 else QColor(55, 115, 155, 35))
    painter.restore()


class PerformanceBackdrop:
    """Keep one screen-sized backdrop for a running show; animation draws on top."""
    def __init__(self):
        self.key = self.pixmap = None

    def draw(self, painter, widget, theme, stage):
        ratio = widget.devicePixelRatioF()
        key = (widget.width(), widget.height(), ratio, theme, stage, stage_image('stage-scenery').cacheKey())
        if key != self.key:
            surface = QPixmap(round(widget.width()*ratio), round(widget.height()*ratio))
            surface.setDevicePixelRatio(ratio)
            brush = QPainter(surface)
            paint_stage(brush, widget.rect(), theme, stage)
            brush.end()
            self.key, self.pixmap = key, surface
        painter.drawPixmap(0, 0, self.pixmap)


def paint_lights(painter, rect, name, elapsed):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    w, h = rect.width(), rect.height()
    for i in range(12):
        x = w*((i*17 % 41)/100 if i%2 else .61+(i*13 % 37)/100)
        if name == 'ocean':
            y = h*((.9 + i*.17 - elapsed*.045) % 1)
            painter.setPen(QPen(QColor(207,250,247,132),1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(x,y), 2+i%4, 2+i%4)
        elif name == 'sakura':
            y = h*((i*.17 + elapsed*.065) % 1)
            painter.setPen(Qt.NoPen);painter.setBrush(QColor(255,222,227,166))
            painter.drawEllipse(QPointF(x+7*math.sin(elapsed+i),y), 3.5, 1.7)
        else:
            y = h*(.04+(i*19 % 69)/100)
            alpha = int(100+70*math.sin(elapsed*1.8+i*2))
            painter.setPen(QPen(QColor(255,234,175,alpha),1))
            painter.drawLine(QPointF(x-2,y),QPointF(x+2,y))
            painter.drawLine(QPointF(x,y-2),QPointF(x,y+2))
    painter.restore()


class StagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);self.theme='';self.stage=0;self.setMinimumHeight(110)
        activity_images().ready.connect(self.update)

    def set_scene(self, theme, stage):
        self.theme,self.stage=theme,stage;self.update()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 8, 8)
        painter.setClipPath(clip)
        paint_stage(painter,self.rect(),self.theme,self.stage)
        singer = stage_image('tianyi-stage')
        if not singer.isNull():
            height = self.height()*.92
            width = height*singer.width()/singer.height()
            target = QRectF((self.width()-width)/2, self.height()-height-3, width, height)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(target, singer, QRectF(singer.rect()))
        painter.end()
