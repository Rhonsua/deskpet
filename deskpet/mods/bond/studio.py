"""Shared reading surfaces and local illustrations for the activity windows."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .scrapbook import ScrapbookArt, activity_images


def dark_theme():
    return QApplication.palette().color(QPalette.Window).lightness() < 128


def activity_style(dark):
    if dark:
        page, paper, field, ink, muted = '#17232e', '#253440', '#1d2c38', '#f3f5f3', '#c1cdd0'
        line, tint, teal, on_teal, hover = '#4c616b', '#304a54', '#9de1d6', '#153c3c', '#3c5662'
        wash, banner = 'rgba(30,44,56,245)', 'rgba(28,43,56,244)'
    else:
        page, paper, field, ink, muted = '#f3f1eb', '#fffdf8', '#fffefa', '#243643', '#4b6166'
        line, tint, teal, on_teal, hover = '#b9cdcd', '#e0edeb', '#236760', '#ffffff', '#d5e8e5'
        wash, banner = 'rgba(255,253,248,241)', 'rgba(250,249,242,237)'
    return f"""
        QDialog {{background:{page};}}
        QWidget {{color:{ink};font:10pt "Microsoft YaHei UI";}}
        QLabel,QCheckBox,QWidget#advancedContent {{background:transparent;}}
        QTabWidget::pane,QScrollArea,QStackedWidget,QScrollArea > QWidget > QWidget,QWidget#homeContent {{background:transparent;border:0;}}
        QTabBar::tab {{background:{paper};color:{muted};padding:7px 12px;border:0;border-bottom:2px solid {line};}}
        QTabBar::tab:selected {{background:{tint};color:{ink};border-bottom:3px solid {teal};}}
        QScrollBar:vertical {{background:transparent;width:9px;margin:2px 0;}}
        QScrollBar::handle:vertical {{background:{muted};min-height:25px;border-radius:4px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
        QFrame#hero,QLabel#footer {{background:{banner};border:1px solid {line};border-radius:9px;}}
        QLabel#footer {{padding:5px 10px;}}
        QFrame#card,QFrame#section {{background:{wash};border:1px solid {line};border-radius:12px;}}
        QFrame#entryLine {{background:{line};border:0;}}
        QLabel#heading {{color:{ink};font-size:16pt;font-weight:bold;}}
        QLabel#sectionTitle {{color:{ink};font-size:12pt;font-weight:bold;}}
        QLabel#entryTitle {{color:{ink};font-weight:bold;}}
        QLabel#muted,QLabel#entryState {{color:{muted};}}
        QLabel#entryState[recorded="true"] {{color:{teal};}}
        QPushButton,QComboBox,QSpinBox,QLineEdit {{background:{field};color:{ink};border:1px solid {line};border-radius:7px;padding:6px 10px;}}
        QPushButton:hover,QPushButton:checked,QComboBox:hover {{background:{hover};}}
        QPushButton:focus,QComboBox:focus,QSpinBox:focus,QLineEdit:focus {{border:2px solid {teal};}}
        QPushButton:disabled,QComboBox:disabled,QLineEdit:disabled {{background:{page};color:{muted};border-color:{line};}}
        QPushButton#primary {{background:{teal};color:{on_teal};border:1px solid {teal};font-weight:bold;padding:8px 16px;}}
        QPushButton#primary:focus {{border:2px solid {ink};}}
        QPushButton#primary:disabled {{background:{tint};color:{muted};border-color:{line};}}
        QComboBox QAbstractItemView {{background:{field};color:{ink};selection-background-color:{tint};selection-color:{ink};}}
        QCheckBox {{spacing:6px;}}
        QProgressBar {{background:{line};border:0;border-radius:3px;}}
        QProgressBar::chunk {{background:{teal};border-radius:3px;}}
        QPushButton#answer {{text-align:left;background:{field};border:1px solid {line};}}
        QPushButton#answer:hover:enabled,QPushButton#answer:focus {{background:{hover};border:2px solid {teal};}}
        QPushButton#answer[result="correct"] {{background:{tint};border:2px solid {teal};}}
        QPushButton#answer[result="picked"] {{background:{page};border:2px dashed {muted};}}
        QLabel#answerKey {{background:{tint};color:{teal};border-radius:7px;font-weight:bold;}}
        QFrame#programSlot {{background:{paper};border:1px solid {line};border-radius:7px;}}
        QFrame#programSlot[cue="current"] {{background:{tint};border:2px solid {teal};}}
    """


def set_role(widget, key, value):
    if widget.property(key) != value:
        widget.setProperty(key, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class ArtStamp(QWidget):
    def __init__(self, art, name='', size=76):
        super().__init__()
        self.art, self.name = art, name
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_name(self, name):
        if name != self.name:
            self.name = name
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.art.draw(painter, self.name, QRectF(self.rect()).adjusted(2, 2, -2, -2))
        painter.end()


class IllustratedHeader(QFrame):
    """Ink-colored cover with its reading area on the left and a watercolor on the right."""
    def __init__(self, title, detail, illustration, art=None):
        super().__init__()
        self.setObjectName('illustratedHeader')
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 8, 14, 8)
        words = QVBoxLayout()
        words.setSpacing(3)
        row.addLayout(words, 1)
        self.title = QLabel(title)
        self.detail = QLabel(detail)
        for label in (self.title, self.detail):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            words.addWidget(label)
        self.title.setStyleSheet('color:#fff9ed;font-size:16pt;font-weight:bold;')
        self.detail.setStyleSheet('color:#d5ebe6;')
        self.stamp = ArtStamp(art or ScrapbookArt(activity_images()), illustration, 74)
        if art is None:
            activity_images().ready.connect(self.stamp.update)
        row.addWidget(self.stamp)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(bounds, 12, 12)
        painter.setClipPath(clip)
        gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
        gradient.setColorAt(0, QColor('#23384c'))
        gradient.setColorAt(1, QColor('#325a60'))
        painter.fillRect(bounds, gradient)
        painter.setPen(QPen(QColor(179, 225, 206, 55), 1.2))
        center = QPointF(bounds.right()-35, bounds.height()*.42)
        for radius in (51, 60, 68):
            painter.drawEllipse(center, radius, radius)
        painter.end()
