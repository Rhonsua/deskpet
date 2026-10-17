"""Compact, calm music and companion panels."""
from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QSlider,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QProgressBar, QComboBox,
)

from pet_store import FOODS


STYLE = """
QWidget { color: #293D54; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QWidget#MusicWindow { background: #F2F6FA; }
QLabel { background: transparent; border: none; }
QLabel#Title { font-size: 25px; font-weight: 700; color: #203B53; }
QLabel#Subtle, QLabel#Status { color: #8193A5; font-size: 11px; }
QLabel#SectionTitle { font-size: 14px; font-weight: 600; }
QLabel#SongTitle { font-size: 17px; font-weight: 600; }
QLabel#Eyebrow { font-size: 10px; color: #6B99A1; }
QLabel#Badge { background: #E2F0F2; color: #48808D; border-radius: 10px; padding: 5px 10px; }
QLabel#EmptyTitle { font-size: 14px; color: #637D91; }
QFrame#Card { background: #FFFFFF; border: 1px solid #E7EDF3; border-radius: 18px; }
QPushButton { background: #ECF2F6; border: none; border-radius: 10px; padding: 9px 13px; color: #49667E; }
QPushButton:hover { background: #DDE9F0; }
QPushButton:pressed { background: #CCDFE8; }
QPushButton#Primary { background: #4E9CAB; color: #FFFFFF; font-weight: 600; }
QPushButton#Primary:hover { background: #3C8797; }
QPushButton#Play { background: #294C66; color: white; border-radius: 16px; padding: 8px 16px; }
QPushButton#Play:hover { background: #386781; }
QPushButton#Transport { border-radius: 14px; min-width: 24px; font-size: 18px; padding: 4px 10px; }
QComboBox { background: #FFFFFF; border: 1px solid #E1EAF1; padding: 8px 12px; border-radius: 9px; min-width: 100px; }
QComboBox::drop-down { border: none; width: 20px; }
QListWidget { background: transparent; border: none; outline: none; padding: 0; }
QListWidget::item { padding: 13px 12px; border-radius: 9px; margin-bottom: 3px; color: #526C82; }
QListWidget::item:hover { background: #F1F7FA; }
QListWidget::item:selected { background: #E6F2F3; color: #2C7A89; }
QSlider::groove:horizontal { height: 4px; background: #E7EEF3; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #69ABB5; border-radius: 2px; }
QSlider::handle:horizontal { background: #FFFFFF; border: 2px solid #69ABB5; width: 8px; height: 8px; margin: -4px 0; border-radius: 6px; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: transparent; color: #8A9AAB; padding: 10px 18px; margin: 0 8px 12px 0; border-radius: 11px; }
QTabBar::tab:selected { background: #FFFFFF; color: #345F77; font-weight: 600; }
QTabBar::tab:hover { color: #345F77; }
QProgressBar { background: #EAF0F5; border: none; border-radius: 4px; height: 7px; text-align: center; }
QProgressBar::chunk { background: #72B3B9; border-radius: 4px; }
QToolTip { background: #294C66; color: white; border: none; padding: 6px; }
QScrollBar:vertical { width: 5px; background: transparent; }
QScrollBar::handle:vertical { background: #CDDAE4; border-radius: 2px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def card():
    frame = QFrame()
    frame.setObjectName('Card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return frame, layout


def button(text, callback, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def sprite_bounds(pixmap):
    """Ignore isolated alpha specks when fitting a sprite into its display area."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    pixels = image.constBits()
    stride = image.bytesPerLine()
    rows, columns = [], [0] * width
    for y in range(height):
        count = 0
        for x in range(width):
            if pixels[y * stride + x * 4 + 3] >= 160:
                count += 1
                columns[x] += 1
        if count >= max(4, width // 100):
            rows.append(y)
    xs = [x for x, count in enumerate(columns) if count >= max(4, height // 100)]
    if rows and xs:
        return QRect(xs[0], rows[0], xs[-1] - xs[0] + 1, rows[-1] - rows[0] + 1)
    return pixmap.rect()


def build(panel):
    panel.setObjectName('MusicWindow')
    panel.setWindowTitle('天依的小电台')
    panel.setStyleSheet(STYLE)
    panel.resize(480, 680)
    panel.setMinimumSize(460, 620)
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(26, 25, 26, 18)
    outer.setSpacing(16)
    header = QHBoxLayout()
    heading = QVBoxLayout()
    heading.setSpacing(5)
    heading.addWidget(label('天依的小电台', 'Title'))
    heading.addWidget(label('把喜欢的歌，慢慢听完。', 'Subtle'))
    header.addLayout(heading)
    header.addStretch()
    header.addWidget(label('本地音乐', 'Badge'))
    outer.addLayout(header)
    panel.tabs = QTabWidget()
    outer.addWidget(panel.tabs, 1)
    music = QWidget()
    music_layout = QVBoxLayout(music)
    music_layout.setContentsMargins(0, 0, 0, 0)
    music_layout.setSpacing(14)
    panel.tabs.addTab(music, '听歌')

    now_card, now = card()
    identity = QHBoxLayout()
    panel.cover = QLabel()
    panel.cover.setFixedSize(78, 88)
    panel.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
    identity.addWidget(panel.cover)
    title_layout = QVBoxLayout()
    title_layout.setContentsMargins(12, 0, 0, 0)
    title_layout.setSpacing(5)
    title_layout.addWidget(label('和天依一起听', 'Eyebrow'))
    panel.song_title = label('今天，想听什么？', 'SongTitle')
    panel.song_title.setWordWrap(True)
    title_layout.addWidget(panel.song_title)
    panel.song_meta = label('从你的本地歌单开始', 'Subtle')
    title_layout.addWidget(panel.song_meta)
    identity.addLayout(title_layout, 1)
    now.addLayout(identity)
    panel.seek = QSlider(Qt.Orientation.Horizontal)
    panel.seek.setRange(0, 0)
    panel.seek.sliderReleased.connect(panel.seek_to)
    now.addWidget(panel.seek)
    panel.time = label('00:00 / 00:00', 'Subtle')
    panel.time.setAlignment(Qt.AlignmentFlag.AlignCenter)
    now.addWidget(panel.time)
    controls = QHBoxLayout()
    controls.addStretch()
    previous = button('‹', lambda: panel.step(-1), 'Transport')
    previous.setToolTip('上一首')
    controls.addWidget(previous)
    panel.play_button = button('播放', panel.toggle, 'Play')
    panel.play_button.setFixedWidth(100)
    panel.play_button.setFixedHeight(40)
    controls.addWidget(panel.play_button)
    following = button('›', lambda: panel.step(1), 'Transport')
    following.setToolTip('下一首')
    controls.addWidget(following)
    controls.addStretch()
    now.addLayout(controls)
    volume_row = QHBoxLayout()
    volume_row.addWidget(label('音量', 'Subtle'))
    panel.volume = QSlider(Qt.Orientation.Horizontal)
    panel.volume.setRange(0, 100)
    panel.volume.setValue(int(panel.settings.value('volume', 60)))
    panel.volume.valueChanged.connect(lambda n: panel.audio.setVolume(n / 100))
    panel.audio.setVolume(panel.volume.value() / 100)
    volume_row.addWidget(panel.volume)
    now.addLayout(volume_row)
    music_layout.addWidget(now_card)

    list_card, playlist = card()
    list_heading = QHBoxLayout()
    panel.queue_label = label('我的歌单', 'SectionTitle')
    list_heading.addWidget(panel.queue_label)
    list_heading.addStretch()
    list_heading.addWidget(button('+ 添加歌曲', panel.add_files, 'Primary'))
    playlist.addLayout(list_heading)
    panel.list_stack = QStackedWidget()
    empty = QWidget()
    empty_layout = QVBoxLayout(empty)
    empty_layout.addStretch()
    empty_title = label('这里，留给你喜欢的歌', 'EmptyTitle')
    empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_layout.addWidget(empty_title)
    hint = label('拖入 MP3，或者点击“添加歌曲”', 'Subtle')
    hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_layout.addWidget(hint)
    empty_layout.addStretch()
    panel.list_stack.addWidget(empty)
    panel.list = QListWidget()
    panel.list.setMinimumHeight(100)
    panel.list_stack.addWidget(panel.list)
    playlist.addWidget(panel.list_stack, 1)
    music_layout.addWidget(list_card, 1)

    companion = QWidget()
    companion_layout = QVBoxLayout(companion)
    companion_layout.setContentsMargins(0, 0, 0, 0)
    companion_layout.setSpacing(14)
    panel.tabs.addTab(companion, '陪伴')
    appearance_row = QHBoxLayout()
    appearance_row.addWidget(label('天依的样子', 'SectionTitle'))
    appearance_row.addStretch()
    panel.appearance = QComboBox()
    panel.appearance.addItem('圆润 Q 版 · V3', 'simple')
    panel.appearance.addItem('精致 Q 版 · V3', 'refined')
    panel.appearance.setCurrentIndex(1 if panel.settings.value('visual_variant', 'refined') == 'refined' else 0)
    panel.appearance.currentIndexChanged.connect(lambda: panel.pet.set_variant(panel.appearance.currentData()))
    appearance_row.addWidget(panel.appearance)
    companion_layout.addLayout(appearance_row)
    growth_card, growth = card()
    growth.addWidget(label('一点一点，成为更好的朋友', 'SectionTitle'))
    panel.growth = label('')
    panel.growth.setWordWrap(True)
    panel.growth.setStyleSheet('line-height: 2; color: #607C91; padding: 10px 0;')
    growth.addWidget(panel.growth)
    panel.experience = QProgressBar()
    panel.experience.setFixedHeight(7)
    panel.experience.setTextVisible(False)
    growth.addWidget(panel.experience)
    companion_layout.addWidget(growth_card)
    food_card, food_layout = card()
    food_layout.addWidget(label('今天也要好好吃饭', 'SectionTitle'))
    food_layout.addWidget(label('用听歌攒下的音符，换一份小点心。', 'Subtle'))
    for name, (cost, *_rest) in FOODS.items():
        row = QHBoxLayout()
        row.addWidget(label(name, 'SectionTitle'))
        row.addStretch()
        row.addWidget(button(f'{cost} 音符 · 投喂', lambda checked=False, food=name: panel.feed(food)))
        food_layout.addLayout(row)
    companion_layout.addWidget(food_card)
    companion_layout.addStretch()
    panel.status = label('双击歌曲播放', 'Status')
    panel.status.setWordWrap(True)
    outer.addWidget(panel.status)


def update_cover(panel, filename):
    pixmap = QPixmap(str(filename))
    if not pixmap.isNull():
        bounds = sprite_bounds(pixmap)
        if not bounds.isEmpty():
            pixmap = pixmap.copy(bounds)
        panel.cover.setPixmap(pixmap.scaled(72, 84, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
