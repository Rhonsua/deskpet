"""Drag-to-select overlays in Qt logical coordinates, one per real work area."""
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class AreaOverlay(QWidget):
    def __init__(self, picker, bounds):
        super().__init__(picker.parent(), Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.picker = picker
        self.start = None
        self.selection = QRect()
        self.setWindowTitle('框选桌宠活动范围')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(bounds)

    def valid_selection(self):
        return (self.selection.width() >= self.picker.minimum.width()
                and self.selection.height() >= self.picker.minimum.height())

    def bounded_point(self, event):
        pos = event.position().toPoint()
        return QPoint(max(0, min(pos.x(), self.width() - 1)),
                      max(0, min(pos.y(), self.height() - 1)))

    def selection_to(self, point):
        # Construct positive inclusive corners directly: QRect.normalized()
        # loses two pixels when constructed from reverse-direction endpoints.
        return QRect(QPoint(min(self.start.x(), point.x()), min(self.start.y(), point.y())),
                     QPoint(max(self.start.x(), point.x()), max(self.start.y(), point.y())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.picker.finish(None)
        elif event.button() == Qt.MouseButton.LeftButton:
            self.activateWindow()
            self.setFocus()
            for overlay in self.picker.overlays:
                overlay.selection = QRect()
                overlay.update()
            self.start = self.bounded_point(event)
            self.selection = QRect(self.start, self.start)
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.selection = self.selection_to(self.bounded_point(event))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.start is not None:
            self.selection = self.selection_to(self.bounded_point(event))
            self.start = None
            if self.valid_selection():
                self.picker.finish(QRect(self.mapToGlobal(self.selection.topLeft()), self.selection.size()))
            else:
                self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.picker.finish(None)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self.picker.done:
            self.picker.finish(None)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 24, 38, 100))
        previous = self.picker.previous
        if previous is not None:
            old = previous.intersected(self.geometry()).translated(-self.x(), -self.y())
            painter.setPen(QPen(QColor('#c2dbe3'), 1, Qt.PenStyle.DashLine))
            if not old.isEmpty():
                painter.drawRect(old.adjusted(1, 1, -1, -1))
        if not self.selection.isEmpty():
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.selection, QColor(77, 188, 221, 35))
            painter.restore()
            color = QColor('#8ce3ff' if self.valid_selection() else '#ffac9a')
            painter.setPen(QPen(color, 2))
            painter.drawRect(self.selection.adjusted(1, 1, -1, -1))
        box = QRect(20, 20, max(1, min(660, self.width() - 40)), 124)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 32, 46, 235))
        painter.drawRoundedRect(box, 12, 12)
        painter.setPen(QColor('#ffffff'))
        font = painter.font()
        font.setFamily('Microsoft YaHei UI')
        font.setPixelSize(16)
        painter.setFont(font)
        selected = (f'已框选 {self.selection.width()} × {self.selection.height()}'
                    if not self.selection.isEmpty() else '在想让桌宠活动的屏幕上拖出矩形')
        if not self.selection.isEmpty() and not self.valid_selection():
            selected += ' · 太小了，请重新框选'
        hint = (f'框选活动范围 · 松开鼠标确认\n{selected}\n'
                f'至少 {self.picker.minimum.width()} × {self.picker.minimum.height()} · Esc / 右键取消\n'
                '确认后桌宠移入框内；手动拖拽不受限制')
        painter.drawText(box.adjusted(16, 12, -16, -12),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, hint)


class ActivityAreaPicker(QObject):
    finished = Signal(object)

    def __init__(self, parent, minimum, previous=None):
        super().__init__(parent)
        self.minimum, self.previous = minimum, previous
        self.overlays = []
        self.done = False

    def open(self):
        app = QApplication.instance()
        # Cancel rather than accepting stale geometry if displays change mid-drag.
        app.screenAdded.connect(self.cancel)
        app.screenRemoved.connect(self.cancel)
        for screen in app.screens():
            screen.availableGeometryChanged.connect(self.cancel)
            overlay = AreaOverlay(self, screen.availableGeometry())
            self.overlays.append(overlay)
            overlay.show()
        self.raise_windows()

    def raise_windows(self):
        for overlay in self.overlays:
            overlay.raise_()
        active = next((w for w in self.overlays if w.geometry().contains(QCursor.pos())),
                      self.overlays[0] if self.overlays else None)
        if active is not None:
            active.activateWindow()
            active.setFocus()

    def cancel(self, *args):
        self.finish(None)

    def finish(self, area):
        if self.done:
            return
        self.done = True
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.finished.emit(area)
        self.deleteLater()
