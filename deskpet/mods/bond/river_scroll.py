"""A fold-out river scroll inside the album, drawn from only the visible slices."""
from pathlib import Path
import random

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .scrapbook import activity_images
from .store import SCROLL_PIECES


ART_DIR = Path(__file__).with_name('assets') / 'river-scroll'


def slice_path(number):
    return ART_DIR / f'{number:02d}.webp'


def candidates(joined, unlocked):
    if joined >= unlocked:
        return []
    rng = random.Random(712 + joined)
    following = range(joined + 2, unlocked + 1)
    options = [joined + 1, *rng.sample(following, min(2, len(following)))]
    # Earlier earned pictures keep a newly earned single piece playable.
    options.extend(rng.sample(range(1, joined + 1), min(3 - len(options), joined)))
    rng.shuffle(options)
    return options


class ScrollStrip(QAbstractScrollArea):
    position_changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.count = 1
        self.tile_width = 1
        self.drag = None
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumHeight(56)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setCursor(Qt.OpenHandCursor)
        self.setAccessibleName('洛天依上河图，拖动画面或使用左右方向键赏画')
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.position_changed.emit())
        activity_images().ready.connect(self.viewport().update)

    def update_extent(self):
        bar = self.horizontalScrollBar()
        at_end = bar.maximum() > 0 and bar.value() == bar.maximum()
        at = bar.value() / self.tile_width
        self.tile_width = max(1, round(self.viewport().height() * 424 / 712))
        bar.setRange(0, max(0, self.count * self.tile_width - self.viewport().width()))
        bar.setPageStep(self.viewport().width())
        bar.setSingleStep(max(1, self.tile_width // 5))
        bar.setValue(bar.maximum() if at_end else round(at * self.tile_width))
        self.position_changed.emit()
        self.viewport().update()

    def visible_range(self):
        start = self.horizontalScrollBar().value()
        end = start + max(1, self.viewport().width()) - 1
        return start // self.tile_width + 1, min(self.count, end // self.tile_width + 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_extent()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    def move_slice(self, step):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() + step * self.tile_width)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = event.position().x(), self.horizontalScrollBar().value()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            origin, offset = self.drag
            self.horizontalScrollBar().setValue(round(offset + origin - event.position().x()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.viewport().setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.move_slice(-1 if event.key() == Qt.Key_Left else 1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor('#fffdf8'))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        offset = self.horizontalScrollBar().value()
        first, last = self.visible_range()
        for number in range(first, last + 1):
            left = (number - 1) * self.tile_width - offset
            image = activity_images().get(slice_path(number))
            if not image.isNull():
                painter.drawPixmap(QRect(left, 0, self.tile_width, self.viewport().height()), image)
        if self.count < SCROLL_PIECES:
            edge = self.count * self.tile_width - offset
            painter.setPen(QPen(QColor('#87b2c1'), 2, Qt.DashLine))
            painter.drawLine(edge, 3, edge, self.viewport().height()-3)
        painter.end()


class RiverFolio(QWidget):
    completed = Signal()

    def __init__(self, store, parent):
        super().__init__(parent)
        self.store = store
        self.joined = self.unlocked = 0
        self.puzzle = False
        self.options = []
        self.setObjectName('riverFolio')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet('''
            QWidget#riverFolio {background:#faf7eb;border:1px solid #c7d5ca;border-radius:5px;}
            QLabel {background:transparent;color:#3c5658;}
            QLabel#riverTitle {font-size:20px;font-weight:700;color:#284b57;}
            QPushButton, QToolButton {background:#f5f2e6;color:#365658;border:1px solid #acbdb3;
                border-radius:5px;padding:3px 7px;}
            QPushButton:checked, QToolButton:hover {background:#d6ece7;color:#20534d;}
            QPushButton:disabled {color:#858d86;border-color:#d6dace;}
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(3)
        title = QLabel('洛天依上河图')
        title.setObjectName('riverTitle')
        header.addWidget(title, 1)
        self.modes = QButtonGroup(self)
        for name, puzzle in (('赏画', False), ('拼图', True)):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setChecked(not puzzle)
            self.modes.addButton(button, int(puzzle))
            button.clicked.connect(lambda checked=False, value=puzzle: self.set_mode(value))
            header.addWidget(button)
        layout.addLayout(header)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.strip = ScrollStrip(self)
        layout.addWidget(self.strip, 1)
        self.tray = QWidget()
        choices = QHBoxLayout(self.tray)
        choices.setContentsMargins(0, 0, 0, 0)
        self.buttons = []
        for index in range(3):
            button = QToolButton()
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setFixedHeight(53)
            button.setIconSize(QSize(43, 47))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(chr(65 + index))
            button.setAccessibleName('选择画片 ' + button.text())
            button.clicked.connect(lambda checked=False, i=index: self.answer(i))
            choices.addWidget(button)
            self.buttons.append(button)
        layout.addWidget(self.tray)
        navigation = QHBoxLayout()
        self.previous = QPushButton('‹  前一幅')
        self.next = QPushButton('后一幅  ›')
        self.position = QLabel()
        self.position.setAlignment(Qt.AlignCenter)
        for control in (self.previous, self.position, self.next):
            navigation.addWidget(control)
        layout.addLayout(navigation)
        self.previous.clicked.connect(lambda: self.strip.move_slice(-1))
        self.next.clicked.connect(lambda: self.strip.move_slice(1))
        self.strip.position_changed.connect(self.show_position)
        activity_images().ready.connect(self.load_choices)
        self.set_mode(False)

    def show_position(self):
        bar = self.strip.horizontalScrollBar()
        first, last = self.strip.visible_range()
        self.position.setText(f'{first:02d}–{last:02d} / {self.strip.count:02d}')
        self.previous.setEnabled(bar.value() > 0)
        self.next.setEnabled(bar.value() < bar.maximum())

    def set_mode(self, puzzle):
        self.puzzle = puzzle
        self.modes.button(int(puzzle)).setChecked(True)
        self.refresh_progress(reset=True)

    def refresh_progress(self, *, reset=False):
        joined, unlocked = self.store.scroll_joined(), self.store.scroll_unlocked()
        if not reset and (joined, unlocked) == (self.joined, self.unlocked):
            return
        previous_joined = self.joined
        self.joined, self.unlocked = joined, unlocked
        self.strip.count = joined if self.puzzle else unlocked
        self.options = candidates(joined, unlocked) if self.puzzle else []
        self.tray.setVisible(bool(self.options))
        self.layout().activate()
        self.strip.update_extent()
        bar = self.strip.horizontalScrollBar()
        if self.puzzle and (reset or joined != previous_joined):
            bar.setValue(bar.maximum())
        elif reset:
            bar.setValue(0)
        if joined == SCROLL_PIECES:
            hint = '十八幅已连成一卷，纪念已收入「日常留笺」。'
        elif self.puzzle and self.options:
            hint = '从已获得的画片里选出能接上卷尾的那幅。'
        elif unlocked == SCROLL_PIECES:
            hint = '十八幅已经集齐。可以拖动赏画，或切到「拼图」接好整卷。'
        elif self.puzzle:
            hint = '已拼到卷尾。每天首次摸头、投喂、聊天、听歌或安静陪伴满 10 分钟、完成小游戏，各得一幅。'
        else:
            hint = '每天首次摸头、投喂、聊天、听歌或安静陪伴满 10 分钟、完成小游戏，各得一幅。'
        self.hint.setText(f'已收集 {unlocked}/{SCROLL_PIECES} 幅 · 已拼好 {joined} 幅\n{hint}')
        for index, button in enumerate(self.buttons):
            button.setVisible(index < len(self.options))
            button.setIcon(QIcon())
        self.load_choices()
        self.show_position()

    def load_choices(self):
        for index, number in enumerate(self.options):
            button = self.buttons[index]
            if button.icon().isNull():
                image = activity_images().get(slice_path(number))
                if not image.isNull():
                    button.setIcon(QIcon(image))

    def answer(self, index):
        if not self.puzzle or not 0 <= index < len(self.options):
            return
        if self.store.join_scroll(self.options[index]):
            self.refresh_progress()
            if self.joined == SCROLL_PIECES:
                self.completed.emit()
        elif self.store.scroll_joined() != self.joined or self.store.scroll_unlocked() != self.unlocked:
            self.refresh_progress()
        else:
            self.hint.setText('色带还没对齐。看看右边的轮廓，再选一次吧。')
