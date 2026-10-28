"""Small vector effects on an input-transparent layer, clipped behind the pet."""
import math
from PySide6.QtCore import QPointF, Qt, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient, QRegion
from PySide6.QtWidgets import QWidget


def _heart(p, x, y, size, color):
    p.save()
    p.translate(x, y)
    p.scale(size, size)
    path = QPainterPath()
    path.moveTo(0, .8)
    path.cubicTo(-1.6, -.2, -1, -1.5, 0, -.6)
    path.cubicTo(1, -1.5, 1.6, -.2, 0, .8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


def _spark(p, x, y, size, color):
    p.setPen(QPen(color, 1.2))
    p.drawLine(QPointF(x-size, y), QPointF(x+size, y))
    p.drawLine(QPointF(x, y-size), QPointF(x, y+size))


def _note(p, x, y, size, color):
    p.save()
    p.translate(x, y)
    p.scale(size, size)
    p.setPen(QPen(color, 1.3))
    p.drawLine(QPointF(1, 0), QPointF(1, -7))
    p.drawLine(QPointF(1, -7), QPointF(5, -5))
    p.setBrush(color)
    p.drawEllipse(QPointF(-.8, .5), 2.2, 1.5)
    p.restore()


def draw_effects(p, size, scale, activity, elapsed, now, music_beat=None):
    from music_tools.clock import beat_values
    synced = beat_values(music_beat) if activity == 'sing' else None
    beat_clock = (synced[0] + synced[1]) if synced else elapsed / .6
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)
    w = size.width()/scale
    center = QPointF(w/2, 280)
    if activity in ('sing', 'turn', 'sleep', 'phone', 'happy', 'head_rub', 'mouse_wave', 'eat', 'level_up'):
        beat = .5+.5*math.cos(beat_clock*math.tau) if synced else .5-.5*math.cos(beat_clock*math.tau)
        color = QColor('#9acbd5' if activity not in ('happy', 'head_rub', 'eat', 'level_up') else '#e3bdcf')
        color.setAlpha(round(22 + (12*beat if activity in ('sing', 'turn') else 0)))
        glow = QRadialGradient(center, 100 if activity in ('sleep', 'phone') else 78)
        glow.setColorAt(0, color)
        edge = QColor(color)
        edge.setAlpha(0)
        glow.setColorAt(1, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(center, 102 if activity in ('sleep', 'phone') else 80, 16)
    if activity in ('sing', 'turn'):
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(2):
            pulse = (beat_clock+i*.5) % 1
            p.setPen(QPen(QColor(121, 191, 206, round(48*(1-pulse))), .8))
            p.drawEllipse(center, 49+pulse*23, 7+pulse*5)
        for i in range(6):
            phase = (beat_clock*.138+i/6) % 1
            x = (24 if i % 2 == 0 else w-25) + math.sin(elapsed*1.5+i)*5
            color = QColor(102, 172, 191, round(110*math.sin(math.pi*phase)))
            _note(p, x, 224-phase*152, .8+(i % 3)*.12, color)
    elif activity in ('happy', 'head_rub', 'level_up'):
        duration = 2.2 if activity == 'head_rub' else 3 if activity == 'level_up' else 1.7
        fade = max(0, min(1, elapsed/.15, (duration-elapsed)/.3))
        for i in range(5):
            phase = (elapsed*.55+i*.19) % 1
            x = w/2 + (-1 if i % 2 else 1)*(72+7*math.sin(i+elapsed))
            _heart(p, x, 155-90*phase, 4+i % 2,
                   QColor(204, 129, 163, round(145*fade*math.sin(math.pi*phase))))
    elif activity == 'mouse_wave':
        fade = max(0, min(1, elapsed/.2, (2.4-elapsed)/.35))
        for i in range(5):
            phase = elapsed*4+i*1.7
            _spark(p, w/2-75+math.cos(phase*.4)*13, 120+i*15,
                   2+1.5*abs(math.sin(phase)), QColor(121, 191, 207, round(135*fade)))
    elif activity == 'sleep':
        for i in range(3):
            phase = (elapsed*.15+i/3) % 1
            x, y = w*.66+phase*20, 184-phase*82
            p.setPen(QPen(QColor(137, 168, 195, round(105*math.sin(math.pi*phase))), 1.3))
            path = QPainterPath(QPointF(x, y))
            path.lineTo(x+7, y)
            path.lineTo(x, y+7)
            path.lineTo(x+7, y+7)
            p.drawPath(path)
    elif activity == 'phone':
        for i in range(3):
            phase = (elapsed*.35+i/3) % 1
            p.setPen(QPen(QColor(134, 201, 223, round(70*math.sin(math.pi*phase))), .9))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(w*.26-25, 224-phase*30), 2+phase*3, 2+phase*3)
    elif activity == 'eat':
        for i in range(4):
            phase = (elapsed*.6+i/4) % 1
            _spark(p, w/2+(-1 if i % 2 else 1)*76, 176-phase*55,
                   2.5+phase*2, QColor(210, 175, 111, round(125*math.sin(math.pi*phase))))
    elif activity == 'lift':
        fade = math.exp(-3*elapsed)
        p.setPen(QPen(QColor(117, 182, 198, round(160*fade)), 1.3))
        for sign in (-1, 1):
            x = w/2+sign*77
            p.drawLine(QPointF(x, 95), QPointF(x+sign*4, 81))
            p.drawLine(QPointF(x+sign*6, 105), QPointF(x+sign*10, 96))
    elif activity == 'land':
        phase = min(1, elapsed/.65)
        p.setPen(QPen(QColor(129, 185, 197, round(105*(1-phase))), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(center, 34+42*phase, 4+7*phase)
    elif activity == 'idle':
        for i in range(2):
            pulse = max(0, math.sin(now*.75+i*3))**8
            _spark(p, 31 if i == 0 else w-32, 172 if i == 0 else 111,
                   1.2+1.3*pulse, QColor(143, 187, 198, round(75*pulse)))
    p.restore()


class PetEffects(QWidget):
    def __init__(self, pet):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus)
        super().__init__(pet, flags)
        self.pet = pet
        self.setWindowTitle('天依 · 动效')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.teleporting = False

    def sync(self):
        teleporting = getattr(getattr(self.pet, 'teleport_controller', None), 'active', False)
        raise_cloud = teleporting and not self.teleporting
        self.teleporting = teleporting
        visible = (self.pet.isVisible() and not self.pet.dock_edge
                   and (teleporting or self.pet.panel.effects_toggle.isChecked()))
        if not visible:
            if self.isVisible():
                self.hide()
            return
        geometry = self.pet.geometry()
        if teleporting:
            body = self.pet.teleport_body
            diameter = math.ceil(math.hypot(body.width(), body.height()) + 56)
            center = QPointF(self.pet.pos()) + body.center()
            geometry = QRect(round(center.x()-diameter/2), round(center.y()-diameter/2), diameter, diameter)
        if self.geometry() != geometry:
            self.setGeometry(geometry)
        if not self.isVisible():
            self.show()
        if raise_cloud:
            self.raise_()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.teleporting:
            from teleport_effects import draw_teleport
            draw_teleport(p, QRectF(self.rect()), self.pet.teleport_body,
                          self.pet.teleport_controller.visual)
            p.end()
            return
        # The native layer stays input-transparent even where effects have alpha.
        # Cutting out the exact current body silhouette makes it appear behind
        # the character without changing the pet's hit region or window mask.
        if not self.pet.hit_region.isEmpty():
            p.setClipRegion(QRegion(self.rect()).subtracted(self.pet.hit_region))
            draw_effects(p, self.size(), self.pet.scale, self.pet.behavior.activity,
                         self.pet.behavior.activity_elapsed, self.pet.phase,
                         self.pet.current_music_beat(self.pet.behavior.activity))
        p.end()
