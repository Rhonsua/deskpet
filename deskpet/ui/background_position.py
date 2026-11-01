"""Interactive crop placement; previews stay local and cancel restores the view."""
from PySide6.QtCore import Qt, QRectF, Signal, QSignalBlocker
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QPushButton, QDialogButtonBox)
from .background import BackgroundPlacement, background_crop, GLASS_STYLE


class BackgroundPreview(QWidget):
    placement_changed = Signal(object)

    def __init__(self, surface, parent=None):
        super().__init__(parent)
        self.image = surface.surface_image
        self.aspect = surface.width() / max(1, surface.height())
        self.placement = surface.surface_placement
        self.drag_start = None
        self.setMinimumSize(240, 180)
        self.setFixedHeight(220)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('按住左键拖动图片，选择想显示的区域')

    def image_rect(self):
        area = self.rect().adjusted(10, 10, -10, -10)
        width = min(area.width(), area.height() * self.aspect)
        height = width / self.aspect
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def set_placement(self, value):
        self.placement = BackgroundPlacement.read(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#DFEAF0'))
        area = self.image_rect()
        if not self.image.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(area, self.image,
                               background_crop(self.image.size(), area.size(), self.placement))
        painter.setPen(QPen(QColor('#8BA9B8'), 1))
        painter.drawRect(area)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.image_rect().contains(event.position()):
            self.drag_start = event.position()
            self.drag_placement = self.placement
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start is None or self.image.isNull():
            return super().mouseMoveEvent(event)
        area = self.image_rect()
        crop = background_crop(self.image.size(), area.size(), self.drag_placement)
        delta = event.position() - self.drag_start
        extra_x = self.image.width() - crop.width()
        extra_y = self.image.height() - crop.height()
        x, y = self.drag_placement.x, self.drag_placement.y
        if extra_x > .01:
            x -= delta.x() * crop.width() / area.width() / extra_x * 100
        if extra_y > .01:
            y -= delta.y() * crop.height() / area.height() / extra_y * 100
        self.placement_changed.emit(BackgroundPlacement.read(dict(x=x, y=y, zoom=self.placement.zoom)))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class BackgroundPositionDialog(QDialog):
    def __init__(self, surface):
        super().__init__(surface)
        self.surface = surface
        self.original = surface.surface_placement
        self.setWindowTitle('调整背景位置')
        self.setStyleSheet(GLASS_STYLE + 'QDialog { background: #F1F7FA; }')
        self.resize(440, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('拖动预览调整位置，也可以使用下面的滑块。'))
        self.preview = BackgroundPreview(surface)
        self.preview.placement_changed.connect(self.set_controls)
        layout.addWidget(self.preview)
        self.sliders = {}
        self.values = {}
        for key, label, minimum, maximum in (
                ('x', '左右位置', 0, 100), ('y', '上下位置', 0, 100), ('zoom', '放大', 100, 300)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setValue(getattr(self.original, key))
            slider.setAccessibleName(label)
            slider.valueChanged.connect(self.apply_preview)
            row.addWidget(slider, 1)
            value = QLabel()
            value.setMinimumWidth(42)
            row.addWidget(value)
            self.sliders[key] = slider
            self.values[key] = value
            layout.addLayout(row)
        hint = QLabel('预览范围与当前窗口一致。某个方向无法移动时，可以先放大一点。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        reset = QPushButton('居中并重置缩放')
        reset.setAutoDefault(False)
        reset.clicked.connect(lambda: self.set_controls(BackgroundPlacement()))
        row.addWidget(reset)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('保存位置')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        self.apply_preview()

    def set_controls(self, placement):
        for key, slider in self.sliders.items():
            with QSignalBlocker(slider):
                slider.setValue(getattr(placement, key))
        self.apply_preview()

    def apply_preview(self, *unused):
        placement = BackgroundPlacement.read({key: slider.value() for key, slider in self.sliders.items()})
        self.preview.set_placement(placement)
        self.surface.set_placement(placement)
        for key, value in self.values.items():
            value.setText(str(getattr(placement, key)) + '%')

    def reject(self):
        self.surface.set_placement(self.original)
        super().reject()
