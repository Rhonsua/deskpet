"""Small, deterministic painted stages shared by games and previews."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

PALETTES=[('#182b50','#415b81'),('#20305c','#725f97'),('#183b46','#3c8b93'),
          ('#173a53','#6860ad'),('#40284e','#98678c'),('#304558','#9b8e58')]


def paint_stage(painter, rect, theme, stage, elapsed=0, *, performance=False, intensity=1.0):
    """Draw a bounded scene; elapsed=0 gives a completely static preview."""
    index=max(0,min(len(PALETTES)-1,int(stage)))
    if theme in ('night','ocean','sakura','gold'):
        index={'night':0,'ocean':2,'sakura':4,'gold':5}[theme]
    else:
        theme={2:'ocean',4:'sakura',5:'gold'}.get(index,'night')
    intensity=max(0.,min(1.,float(intensity)))
    painter.save()
    painter.translate(rect.x(),rect.y())
    painter.scale(rect.width()/1000,rect.height()/600)
    painter.setClipRect(QRectF(0,0,1000,600))
    painter.setRenderHint(QPainter.Antialiasing)
    gradient=QLinearGradient(0,0,0,600)
    gradient.setColorAt(0,QColor(PALETTES[index][0]));gradient.setColorAt(1,QColor(PALETTES[index][1]))
    painter.fillRect(QRectF(0,0,1000,600),gradient)
    painter.setPen(Qt.NoPen)
    if theme=='ocean':
        for x in (70,350,720,970):
            painter.setBrush(QColor(161,239,244,22 if performance else 12))
            painter.drawPolygon(QPolygonF([QPointF(x,0),QPointF(x+120,0),QPointF(x+290,600),QPointF(x+180,600)]))
        for row in range(3):
            wave=QPainterPath();wave.moveTo(0,480+row*37)
            for x in range(0,1001,20):wave.lineTo(x,480+row*37+12*math.sin(x/95+row+elapsed*.5))
            painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor(153,235,235,85),3));painter.drawPath(wave)
        painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor(186,250,249,125),2))
        for i in range(15):
            x=(i*137+25)%1000
            if not performance and 170<x<830:continue
            y=(i*113+55-int(elapsed*18))%500
            r=5+(i%4)*3;painter.drawEllipse(QPointF(x,y),r,r)
    elif theme=='sakura':
        painter.setPen(QPen(QColor(70,38,61,210),9,Qt.SolidLine,Qt.RoundCap))
        for side in (0,1):
            painter.drawLine(QPointF(1000*side,25),QPointF(155 if side==0 else 845,115))
            painter.drawLine(QPointF(95 if side==0 else 905,75),QPointF(120 if side==0 else 880,20))
        painter.setPen(Qt.NoPen)
        for i in range(32):
            x=(i*179+35+math.sin(elapsed*.8+i)*18)%1000
            if not performance and 170<x<830:continue
            y=(i*97+30+elapsed*(12+i%4))%480
            painter.save();painter.translate(x,y);painter.rotate(i*31+elapsed*15)
            painter.setBrush(QColor(255,189+(i%3)*12,212,170));painter.drawEllipse(QRectF(-7,-3,14,6));painter.restore()
        for x,y in ((25,24),(67,58),(110,84),(133,35),(975,24),(933,58),(890,84),(867,35)):
            painter.setBrush(QColor(255,203,222,220));painter.drawEllipse(QPointF(x,y),12,10)
    elif theme=='gold':
        for side in (0,1):
            x=0 if side==0 else 1000
            painter.setBrush(QColor(110,23,52,230))
            painter.drawPolygon(QPolygonF([QPointF(x,0),QPointF(x+(175 if side==0 else -175),0),QPointF(x+(110 if side==0 else -110),430),QPointF(x,510)]))
            painter.setBrush(QColor(255,215,140,32 if performance else 16))
            painter.drawPolygon(QPolygonF([QPointF(x,0),QPointF(x+(130 if side==0 else -130),0),QPointF(600 if side==0 else 400,600)]))
        painter.setPen(QPen(QColor(250,219,145,150),3))
        painter.drawLine(0,35,1000,35)
        for i in range(18):
            x=(i*197+40)%1000
            if not performance and 180<x<820:continue
            y=(i*83+60)%430
            size=3+2*(.5+.5*math.sin(elapsed*2+i))*intensity
            painter.drawLine(QPointF(x-size,y),QPointF(x+size,y));painter.drawLine(QPointF(x,y-size),QPointF(x,y+size))
    if performance:
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(11,18,38,110))
        painter.drawEllipse(QRectF(-100,510,1200,220))
        painter.setBrush(QColor(255,224,164,170))
        for i in range(14):painter.drawEllipse(QPointF(50+i*70,565),5,5)
    painter.restore()


class StagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);self.theme='';self.stage=0;self.setMinimumHeight(110)

    def set_scene(self, theme, stage):
        self.theme,self.stage=theme,stage;self.update()

    def paintEvent(self, event):
        painter=QPainter(self)
        paint_stage(painter,self.rect(),self.theme,self.stage,performance=True)
        painter.end()
