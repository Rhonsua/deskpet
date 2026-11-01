"""Continuous window background and translucent controls."""
from pathlib import Path
from dataclasses import dataclass, asdict
import math
from PySide6.QtCore import Qt, QSaveFile, QIODevice, QSize, QRectF
from PySide6.QtGui import QPixmap,QPainter,QColor,QImageReader
from PySide6.QtWidgets import QWidget

GLASS_STYLE='''
QWidget { background: transparent; color: #142B36; font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: 12px; }
QLineEdit, QPlainTextEdit, QTextBrowser { background: rgba(255,255,255,185); color: #142B36; border: 1px solid rgba(125,156,170,150); border-radius: 7px; padding: 7px; selection-background-color: #B8DDEB; selection-color: #102B39; }
QPushButton, QToolButton, QComboBox { background: rgba(255,255,255,175); color: #142B36; border: 1px solid rgba(125,156,170,150); border-radius: 7px; padding: 7px 12px; }
QPushButton:hover, QToolButton:hover, QComboBox:hover { background: rgba(233,247,255,225); }
QPushButton:pressed, QToolButton:checked { background: rgba(199,229,242,220); }
QPushButton:disabled, QToolButton:disabled { color: #687B84; background: rgba(255,255,255,110); }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: rgba(255,255,255,145); padding: 9px 16px; }
QTabBar::tab:selected { background: rgba(226,244,253,210); border-bottom: 2px solid #4D8C9F; }
QLabel, QCheckBox { background: rgba(255,255,255,135); border-radius: 4px; padding: 2px; }
QScrollArea, QStackedWidget { background: transparent; border: none; }
QScrollBar:vertical { background: rgba(255,255,255,80); width: 12px; }
QScrollBar::handle:vertical { background: rgba(95,137,155,165); min-height: 25px; border-radius: 5px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QComboBox QAbstractItemView, QMenu, QToolTip { background: #F5FAFC; color: #142B36; selection-background-color: #C8E5F1; selection-color: #142B36; }
'''

def save_background(source, destination):
    source=Path(source)
    if source.stat().st_size>30*1024*1024:raise ValueError('请选择小于 30 MB 的图片。')
    reader=QImageReader(str(source));reader.setAutoTransform(True)
    size=reader.size()
    if not size.isValid() or size.width()*size.height()>100_000_000:
        raise ValueError('图片无法读取或尺寸过大。')
    if max(size.width(),size.height())>4096:
        reader.setScaledSize(size.scaled(QSize(4096,4096),Qt.KeepAspectRatio))
    picture=reader.read()
    if picture.isNull():raise ValueError('无法读取这张图片，请选择 PNG、JPG 或 WebP。')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    file=QSaveFile(str(destination))
    if not file.open(QIODevice.WriteOnly):raise OSError(file.errorString())
    if not picture.save(file,'PNG'):
        file.cancelWriting();raise OSError('背景保存失败')
    if not file.commit():raise OSError(file.errorString())



class BackgroundSurface(QWidget):
    surface_color = '#EAF2F6'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.surface_image=QPixmap();self.surface_cover=QPixmap()
        self.surface_placement = BackgroundPlacement()

    def set_placement(self, value):
        self.surface_placement = BackgroundPlacement.read(value)
        self.scale_surface()

    def set_surface(self,path):
        self.surface_image=QPixmap(str(path)) if path and Path(path).is_file() else QPixmap()
        self.scale_surface()

    def scale_surface(self):
        self.surface_cover = QPixmap()
        if not self.surface_image.isNull() and not self.size().isEmpty():
            # Cache only the visible viewport, even when heavily zoomed in.
            self.surface_cover = QPixmap(self.size())
            self.surface_cover.fill(Qt.transparent)
            painter = QPainter(self.surface_cover)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(self.rect()), self.surface_image,
                               background_crop(self.surface_image.size(), self.size(), self.surface_placement))
            painter.end()
        self.update()

    def resizeEvent(self,event):
        super().resizeEvent(event);self.scale_surface()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor(self.surface_color))
        if not self.surface_cover.isNull():
            painter.drawPixmap(0, 0, self.surface_cover)
        painter.end()


@dataclass(frozen=True)
class BackgroundPlacement:
    x: int = 50
    y: int = 50
    zoom: int = 100

    @classmethod
    def read(cls, value=None):
        if isinstance(value, cls):
            value = asdict(value)
        if not isinstance(value, dict):
            value = {}
        def bounded(name, default, low, high):
            try:
                number = float(value.get(name, default))
                return max(low, min(high, round(number))) if math.isfinite(number) else default
            except (ValueError, TypeError, OverflowError):
                return default
        return cls(bounded('x', 50, 0, 100), bounded('y', 50, 0, 100),
                   bounded('zoom', 100, 100, 300))

    def as_dict(self):
        return asdict(self)


def background_crop(image_size, viewport_size, placement=None):
    """Source-image rectangle, always filling the viewport without blank edges."""
    if image_size.isEmpty() or viewport_size.isEmpty():
        return QRectF()
    position = BackgroundPlacement.read(placement)
    scale = max(viewport_size.width() / image_size.width(),
                viewport_size.height() / image_size.height()) * position.zoom / 100
    width = min(image_size.width(), viewport_size.width() / scale)
    height = min(image_size.height(), viewport_size.height() / scale)
    return QRectF((image_size.width() - width) * position.x / 100,
                  (image_size.height() - height) * position.y / 100, width, height)
