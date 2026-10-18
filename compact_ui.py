"""Small on-demand library and settings tool window; the pet is the main surface."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QTabWidget,
    QComboBox, QLineEdit, QStackedWidget, QListWidget, QAbstractItemView,
    QProgressBar, QCheckBox, QScrollArea, QFrame,
)
from music_library import MODES
from pet_store import FOODS
from ui_theme import CONTROL_STYLE, style_combo
from bilibili_player import BilibiliPlayer


COMPACT_STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #394C5B; }
QWidget#PetTools { background: #FAFCFD; }
QDialog { background: #FAFCFD; }
QLabel { background: transparent; }
QLabel#Muted { color: #83929D; font-size: 11px; }
QLabel#Song { font-weight: 600; color: #315D72; font-size: 14px; }
QPushButton { border: 1px solid #D9E4EA; background: #FFFFFF; padding: 6px 10px; border-radius: 4px; }
QPushButton:hover { background: #E9F4F7; border-color: #9FC7D4; }
QPushButton#Play { background: #5E9FB2; color: white; border-color: #5E9FB2; min-width: 50px; }
QComboBox, QLineEdit { border: 1px solid #D9E4EA; border-radius: 4px; background: white; padding: 5px 7px; }
QComboBox::drop-down { border: none; width: 16px; }
QListWidget { border: 1px solid #E0E8ED; border-radius: 4px; background: white; outline: none; }
QListWidget::item { padding: 9px; }
QListWidget::item:selected { color: #346B7C; background: #E1F1F5; }
QListWidget::item:hover { background: #F1F7F9; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #86969F; padding: 8px 17px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #3A7D90; border-bottom-color: #70AAB9; }
QSlider::groove:horizontal { background: #E4EBEF; height: 3px; }
QSlider::sub-page:horizontal { background: #7AACBA; }
QSlider::handle:horizontal { background: #6A9FAF; width: 9px; margin: -3px 0; border-radius: 4px; }
QProgressBar { border: none; background: #E6EFF3; border-radius: 3px; }
QProgressBar::chunk { background: #83B8C5; border-radius: 3px; }
QCheckBox { spacing: 8px; padding: 8px 0; }
""" + CONTROL_STYLE


def text(value, muted=False):
    item = QLabel(value)
    if muted:
        item.setObjectName('Muted')
    return item


def action(value, callback):
    item = QPushButton(value)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    item.clicked.connect(callback)
    return item


def build(panel):
    panel.setObjectName('PetTools')
    panel.setWindowTitle('天依 · 歌单与设置')
    panel.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
    panel.setStyleSheet(COMPACT_STYLE)
    panel.resize(400, 520)
    panel.setMinimumSize(370, 460)
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(12, 8, 12, 10)
    outer.setSpacing(6)
    panel.tabs = QTabWidget()
    outer.addWidget(panel.tabs, 1)
    music = QWidget()
    layout = QVBoxLayout(music)
    layout.setContentsMargins(0, 10, 0, 0)
    layout.setSpacing(8)
    panel.tabs.addTab(music, '音乐')
    panel.cover = QLabel(panel)
    panel.cover.hide()
    panel.song_title = text('添加几首喜欢的歌吧')
    panel.song_title.setObjectName('Song')
    panel.song_title.setWordWrap(True)
    panel.song_title.setMaximumHeight(44)
    layout.addWidget(panel.song_title)
    panel.song_meta = text('本地 MP3', True)
    layout.addWidget(panel.song_meta)
    panel.seek = QSlider(Qt.Orientation.Horizontal)
    panel.seek.setRange(0, 0)
    panel.seek.sliderReleased.connect(panel.seek_to)
    layout.addWidget(panel.seek)
    panel.time = text('00:00 / 00:00', True)
    layout.addWidget(panel.time)
    controls = QHBoxLayout()
    controls.addWidget(action('上一首', lambda: panel.step(-1)))
    panel.play_button = action('播放', panel.toggle)
    panel.play_button.setObjectName('Play')
    controls.addWidget(panel.play_button)
    controls.addWidget(action('下一首', lambda: panel.step(1)))
    panel.mode_choice = QComboBox()
    style_combo(panel.mode_choice)
    for key, name in MODES.items():
        panel.mode_choice.addItem(name, key)
    panel.mode_choice.setCurrentIndex(panel.mode_choice.findData(panel.queue.mode))
    panel.mode_choice.currentIndexChanged.connect(panel.set_mode)
    controls.addWidget(panel.mode_choice)
    layout.addLayout(controls)
    volume = QHBoxLayout()
    volume.addWidget(text('音量', True))
    panel.volume = QSlider(Qt.Orientation.Horizontal)
    panel.volume.setRange(0, 100)
    panel.volume.setValue(int(panel.settings.value('volume', 60)))
    panel.volume.valueChanged.connect(panel.set_volume)
    volume.addWidget(panel.volume)
    layout.addLayout(volume)
    playlists = QHBoxLayout()
    panel.playlist_choice = QComboBox()
    style_combo(panel.playlist_choice)
    panel.playlist_choice.setMinimumContentsLength(5)
    panel.playlist_choice.currentIndexChanged.connect(panel.choose_playlist)
    playlists.addWidget(panel.playlist_choice, 1)
    playlists.addWidget(action('新建', panel.new_playlist))
    panel.playlist_manage = action('管理', panel.manage_playlist)
    playlists.addWidget(panel.playlist_manage)
    layout.addLayout(playlists)
    search = QHBoxLayout()
    panel.search = QLineEdit()
    panel.search.setPlaceholderText('搜索歌曲')
    panel.search.setClearButtonEnabled(True)
    panel.search.textChanged.connect(panel.filter_songs)
    search.addWidget(panel.search, 1)
    search.addWidget(action('+ 歌曲', panel.add_files))
    search.addWidget(action('文件夹', panel.add_folder))
    search.addWidget(action('B站', lambda: panel.tabs.setCurrentIndex(3)))
    layout.addLayout(search)
    panel.queue_label = text('歌单', True)
    layout.addWidget(panel.queue_label)
    panel.list_stack = QStackedWidget()
    empty = text('拖入 MP3 或文件夹\n天依陪你一起听')
    empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
    panel.list_stack.addWidget(empty)
    panel.list = QListWidget()
    panel.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    panel.list_stack.addWidget(panel.list)
    layout.addWidget(panel.list_stack, 1)
    edit = QHBoxLayout()
    edit.addWidget(action('移除', panel.remove_songs))
    edit.addStretch()
    edit.addWidget(action('上移', lambda: panel.move_song(-1)))
    edit.addWidget(action('下移', lambda: panel.move_song(1)))
    layout.addLayout(edit)

    growth_page = QWidget()
    growth = QVBoxLayout(growth_page)
    growth.setContentsMargins(2, 14, 2, 0)
    growth.setSpacing(14)
    panel.tabs.addTab(growth_page, '成长')
    panel.growth = text('')
    panel.growth.setWordWrap(True)
    growth.addWidget(panel.growth)
    panel.experience = QProgressBar()
    panel.experience.setFixedHeight(6)
    panel.experience.setTextVisible(False)
    growth.addWidget(panel.experience)
    growth.addWidget(text('听歌获得音符，可以给天依买点心。', True))
    for name, (cost, *_rest) in FOODS.items():
        growth.addWidget(action(f'投喂{name} · {cost} 音符', lambda checked=False, food=name: panel.feed(food)))
    growth.addStretch()

    settings_page = QScrollArea()
    settings_page.setWidgetResizable(True)
    settings_page.setFrameShape(QFrame.Shape.NoFrame)
    settings_content = QWidget()
    settings_page.setWidget(settings_content)
    settings = QVBoxLayout(settings_content)
    settings.setContentsMargins(2, 14, 2, 0)
    settings.setSpacing(12)
    panel.tabs.addTab(settings_page, '设置')
    panel.startup_toggle = QCheckBox('登录 Windows 后启动桌宠')
    panel.startup_toggle.toggled.connect(panel.toggle_startup)
    settings.addWidget(panel.startup_toggle)
    panel.startup_note = text('只显示天依，不打开歌单，也不自动播放。', True)
    panel.startup_note.setWordWrap(True)
    settings.addWidget(panel.startup_note)
    panel.passthrough_toggle = QCheckBox('鼠标穿透（从系统托盘可关闭）')
    panel.passthrough_toggle.toggled.connect(lambda enabled: panel.pet.set_mouse_passthrough(enabled))
    settings.addWidget(panel.passthrough_toggle)
    settings.addWidget(text('角色外观'))
    panel.appearance = QComboBox()
    style_combo(panel.appearance)
    panel.appearance.addItem('精致 Q 版 · 经典 V3', 'refined')
    panel.appearance.addItem('圆润 Q 版 · 经典 V3', 'simple')
    panel.appearance.setCurrentIndex(0 if panel.settings.value('visual_variant', 'refined') == 'refined' else 1)
    panel.appearance.currentIndexChanged.connect(lambda: panel.pet.set_variant(panel.appearance.currentData()))
    settings.addWidget(panel.appearance)
    settings.addWidget(text('音频输出'))
    panel.output_choice = QComboBox()
    style_combo(panel.output_choice)
    panel.output_choice.addItem('跟随系统默认输出（待读取）', '')
    panel.output_choice.currentIndexChanged.connect(panel.choose_audio_output)
    settings.addWidget(panel.output_choice)
    panel.output_note = text('打开设置或播放本地音乐时读取设备。', True)
    panel.output_note.setWordWrap(True)
    settings.addWidget(panel.output_note)
    tip = text('摸头：点头部\n戳一戳：点身体\n提起：按住后拖动\n边缘探头：拖到边缘后缩回，鼠标经过不展开\n离开边缘：按住探头向桌面内拖回\n鼠标穿透：托盘菜单可随时关闭\n打开菜单：右键或双击天依', True)
    settings.addWidget(tip)
    settings.addStretch()
    panel.bilibili = BilibiliPlayer(panel)
    panel.tabs.addTab(panel.bilibili, 'B站')
    panel.status = text('右键天依，打开互动菜单', True)
    panel.status.setWordWrap(True)
    outer.addWidget(panel.status)
