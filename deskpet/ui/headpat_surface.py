"""Small input surface used only while explicit head petting is available."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from deskpet.animation.headpat_contact import contact_region


class HeadpatSurface(QWidget):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.pet = pet
        self.setWindowTitle('桌宠摸头互动区域')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setMouseTracking(True)
        self.cursor_pose = None

    def sync(self, available):
        pet = self.pet
        region = contact_region(pet.head_region.boundingRect(), pet.scale, retaining=True)
        if not available or not pet.petting or region.isEmpty():
            self.hide()
            self.unsetCursor()
            self.cursor_pose = None
            return
        box = region.boundingRect()
        global_box = box.translated(pet.mapToGlobal(pet.rect().topLeft()))
        if self.geometry() != global_box:
            self.setGeometry(global_box)
        mask = region.translated(-box.topLeft())
        if self.mask() != mask:
            self.setMask(mask)
        pose = pet.glove_cursor_pose
        if self.cursor_pose != pose or not self.isVisible():
            self.setCursor(pet.cursor())
            self.cursor_pose = pose
        if not self.isVisible():
            self.show()
            self.raise_()

    def paintEvent(self, event):
        # Windows ignores fully transparent pixels for hit testing. This one-
        # alpha surface extends beyond the pet window without resizing the pet.
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.pet.end_petting()
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def contextMenuEvent(self, event):
        self.pet.end_petting()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.pet.end_petting()
        else:
            super().keyPressEvent(event)
