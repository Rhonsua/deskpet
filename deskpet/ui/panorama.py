"""A desktop-anchored shop panorama seen through a feathered, click-through window."""
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication

from .background import BackgroundSurface, background_crop
from .shop_art import item_pixmap


def panorama_frame(image, desktop, aperture, dpr=1.):
    """Sample the desktop's cover crop in logical coordinates; allocate only the circle's bounds."""
    frame = QPixmap(round(aperture.width() * dpr), round(aperture.height() * dpr))
    frame.setDevicePixelRatio(dpr)
    frame.fill(Qt.transparent)
    visible = desktop.intersected(aperture)
    if visible.isEmpty() or image.isNull():
        return frame

    cover = background_crop(image.size(), desktop.size())
    units = cover.width() / desktop.width()
    source = QRectF(cover.x() + (visible.x() - desktop.x()) * units,
                    cover.y() + (visible.y() - desktop.y()) * units,
                    visible.width() * units, visible.height() * units)
    local = QRectF(0, 0, aperture.width(), aperture.height())
    fade = QRadialGradient(local.center(), local.width() / 2)
    for stop, alpha in ((0., 255), (.63, 255), (.73, 232), (.83, 152), (.93, 42), (1., 0)):
        fade.setColorAt(stop, QColor(255, 255, 255, alpha))

    painter = QPainter(frame)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawPixmap(QRectF(visible.translated(-aperture.topLeft())), image, source)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    painter.fillRect(local, fade)
    painter.end()
    return frame


class DesktopPanorama(BackgroundSurface):
    def __init__(self, pet, item):
        # An owned tool window would always sit in front of its owner on Windows.
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.pet = pet
        self.key = item.key
        self.desktop = QRect()
        self.opacity_level = 255
        self.thumbnail = item_pixmap(item.key)
        self.setWindowTitle(item.name)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)
        pet.destroyed.connect(self.deleteLater)
        self.set_surface(item.panorama_image)

    def scale_surface(self):
        # The image loader publishes the full-resolution art on the GUI thread.
        # The crop depends on the window's global position as well as its size.
        self.update()

    def sync(self):
        pet = self.pet
        if not pet.isVisible() or pet.isMinimized():
            self.hide()
            return
        opacity = pet.dock_reveal if pet.dock_edge else 1.
        if pet.teleport_controller.active:
            opacity *= pet.teleport_controller.visual.person
        level = round(255 * opacity)
        if level == 0:
            self.hide()
            return

        diameter = round(420 * pet.scale)
        aperture = QRect(pet.pos(), QSize(diameter, diameter))
        aperture.moveCenter(pet.geometry().center())
        # Include taskbars and all joined monitors, including negative origins.
        desktop = pet.screen().virtualGeometry()
        if desktop != self.desktop or aperture != self.geometry():
            self.desktop = desktop
            self.setGeometry(aperture)
            self.update()
        if self.opacity_level != level:
            self.opacity_level = level
            self.setWindowOpacity(level / 255)
        if not self.isVisible():
            self.show()
            self._stack_behind_pet()

    def _stack_behind_pet(self):
        if QApplication.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes

            position = ctypes.windll.user32.SetWindowPos
            position.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
            position.restype = wintypes.BOOL
            # Only place our two HWNDs relative to each other, without activation.
            keep_geometry_and_focus = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
            if position(int(self.winId()), int(self.pet.winId()), 0, 0, 0, 0, keep_geometry_and_focus):
                return
        self.pet.raise_()

    def paintEvent(self, event):
        image = self.thumbnail if self.surface_image.isNull() else self.surface_image
        frame = panorama_frame(image, self.desktop, self.geometry(), self.devicePixelRatioF())
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(QPointF(0, 0), frame)
        painter.end()
