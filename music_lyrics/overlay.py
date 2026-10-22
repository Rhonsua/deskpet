"""Two-line lyric window with persistent appearance and a right-click menu."""
from PySide6.QtCore import Qt, QPoint, QPointF, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QMenu, QColorDialog
from ui_theme import apply_light_palette, CONTROL_STYLE


class LyricsOverlay(QWidget):
    settingsRequested = Signal(dict)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text = ''
        self.font_size = 18
        self.text_color = '#ffffff'
        self.left_passthrough = True
        self.menu_open = self.dialog_open = False
        from .right_click import RightClickAccess
        self.right_click = RightClickAccess(self)
        self.right_click.requested.connect(self._native_menu, Qt.ConnectionType.QueuedConnection)

    def set_options(self, color, left_passthrough):
        if color != self.text_color:
            self.text_color = color
            self.update()
        if self.left_passthrough != left_passthrough:
            self.left_passthrough = left_passthrough
            visible = self.isVisible()
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, left_passthrough)
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, left_passthrough)
            if not left_passthrough:
                self.right_click.stop()
            if visible:
                self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self.left_passthrough:
            self.right_click.start()

    def hideEvent(self, event):
        self.right_click.stop()
        super().hideEvent(event)

    def _native_menu(self, x, y):
        if self.isVisible():
            self.open_menu(QPoint(x, y))

    def contextMenuEvent(self, event):
        self.open_menu(event.globalPos())
        event.accept()

    def make_menu(self):
        menu = QMenu(self)
        apply_light_palette(menu)
        menu.setStyleSheet(CONTROL_STYLE)
        menu.colors = QMenu('歌词颜色', menu)
        menu.addMenu(menu.colors)
        colors = menu.colors
        for name, value in (('白色', '#ffffff'), ('天蓝', '#66ccff'), ('青绿', '#66e0c2'),
                            ('粉色', '#ff9dc7'), ('金黄', '#ffd666')):
            action = colors.addAction(name)
            action.setCheckable(True)
            action.setChecked(self.text_color == value)
            action.triggered.connect(lambda checked=False, color=value: self.settingsRequested.emit({'color': color}))
        colors.addSeparator()
        colors.addAction('自定义颜色…', self.choose_color)
        menu.addSeparator()
        passthrough = menu.addAction('左键穿透（右键仍可设置）')
        passthrough.setCheckable(True)
        passthrough.setChecked(self.left_passthrough)
        passthrough.toggled.connect(lambda enabled: self.settingsRequested.emit({'left_passthrough': enabled}))
        menu.addAction('隐藏歌词', lambda: self.settingsRequested.emit({'enabled': False}))
        hint = menu.addAction('恢复显示：音乐 → 歌词字幕')
        hint.setEnabled(False)
        return menu

    def open_menu(self, position):
        if self.menu_open or self.dialog_open:
            return
        self.menu_open = True
        menu = self.make_menu()
        try:
            menu.exec(position)
        finally:
            self.menu_open = False
            menu.deleteLater()

    def choose_color(self):
        self.dialog_open = True
        try:
            color = QColorDialog.getColor(QColor(self.text_color), None, '选择歌词颜色')
            if color.isValid():
                self.settingsRequested.emit({'color': color.name()})
        finally:
            self.dialog_open = False

    def set_content(self, text, font_size, width):
        text = '\n'.join(text.splitlines()[:2])
        if (text, font_size, width) == (self.text, self.font_size, self.width()):
            return
        self.text, self.font_size = text, font_size
        font = QFont('Microsoft YaHei UI', font_size)
        font.setBold(True)
        metrics = QFontMetrics(font)
        self.resize(width, metrics.lineSpacing() * max(1, len(text.splitlines())) + 12)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont('Microsoft YaHei UI', self.font_size)
        font.setBold(True)
        metrics = QFontMetrics(font)
        for index, line in enumerate(self.text.splitlines()[:2]):
            line = metrics.elidedText(line, Qt.TextElideMode.ElideRight, max(1, self.width() - 14))
            path = QPainterPath()
            x = (self.width() - metrics.horizontalAdvance(line)) / 2
            y = 6 + metrics.ascent() + index * metrics.lineSpacing()
            path.addText(QPointF(x, y), font, line)
            # drawPath fills first, then strokes over half of each thin CJK
            # stem. Paint the outline first and refill the complete glyph last.
            painter.strokePath(path, QPen(QColor(0, 0, 0, 230), 3, Qt.PenStyle.SolidLine,
                                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.fillPath(path, QColor(self.text_color))
