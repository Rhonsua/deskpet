"""Character-first desktop interactions, local dialogue, state animation and a small toolbar."""
import math
import random
import sqlite3
import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion, QTransform, QPen, QDesktopServices, QCursor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
    QProgressBar, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget, QCheckBox,
)

from pet_store import FOODS
from visual_style import (sprite_bounds, update_cover, preferred_variant,
                          APPEARANCE_REVISION, BUILTIN_APPEARANCES)
from ui_theme import CONTROL_STYLE, apply_light_palette
from app_icon import application_icon
from edge_docking import EDGES, clamp_position, dock_position, nearest_edge, edge_gap, pushed_edge
from pet_behavior import MODES, PetBehavior
from singing_motion import SingingRig, singing_pose
from drag_motion import DragSway, interaction_pose
from pointer_follow import PointerFollow
from mouse_interactions import MouseInteractions, REACTION_SECONDS
from pet_effects import PetEffects
from character_packs import (builtin_sources, STATES, DEFAULT_ANCHORS, read_pack,
                             validate_images, selected_folder, discover_packs)


POPUP_STYLE = """
QFrame#PetPopup { background: #FFFFFF; border: 1px solid #AFC8D3; border-radius: 6px; }
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #000000; background: #FFFFFF; }
QLabel { background: transparent; border: none; }
QLabel#Muted { color: #000000; font-size: 11px; }
QPushButton { background: #FFFFFF; border: 1px solid #D9E5EA; padding: 6px 9px; border-radius: 4px; }
QPushButton:hover { background: #FFFFFF; border-color: #000000; }
QPushButton:checked { background: #FFFFFF; color: #000000; border-color: #000000; }
QProgressBar { background: #E7F0F4; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #79AEBE; border-radius: 3px; }
QSlider::groove:horizontal { height: 3px; background: #E1EBF0; }
QSlider::handle:horizontal { width: 9px; background: #75A4B5; margin: -3px 0; border-radius: 4px; }
QCheckBox { spacing: 7px; }
""" + CONTROL_STYLE


def clamp_near(pet, window, above=True):
    screen = QApplication.screenAt(pet.frameGeometry().center()) or QApplication.primaryScreen()
    bounds = screen.availableGeometry().adjusted(8, 8, -8, -8)
    x = pet.x() + (pet.width() - window.width()) // 2
    y = pet.y() - window.height() - 6 if above else pet.y() + pet.height() + 5
    if y < bounds.top():
        y = pet.y() + 20
        x = pet.x() - window.width() - 5 if pet.x() - window.width() > bounds.left() else pet.x() + pet.width() + 5
    window.move(max(bounds.left(), min(x, bounds.right() - window.width())),
                max(bounds.top(), min(y, bounds.bottom() - window.height())))


class Bubble(QFrame):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.pet = pet
        self.setObjectName('PetPopup')
        apply_light_palette(self)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(POPUP_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(220)
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def say(self, value, duration=3400):
        self.label.setText(value)
        self.adjustSize()
        clamp_near(self.pet, self)
        self.show()
        self.timer.start(duration)


class PetToolbar(QFrame):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.pet = pet
        self.setObjectName('PetPopup')
        apply_light_palette(self)
        self.setStyleSheet(POPUP_STYLE)
        self.setFixedWidth(336)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(9)
        title = QHBoxLayout()
        self.name = QLabel('洛天依')
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setWordWrap(True)
        self.name.setStyleSheet('font-weight: 600; color: #000000;')
        title.addWidget(self.name)
        title.addStretch()
        close = QPushButton('收起')
        close.clicked.connect(self.hide)
        title.addWidget(close)
        outer.addLayout(title)
        self.bars = {}
        for key, caption in [('xp', '经验'), ('hunger', '饱食'), ('mood', '心情')]:
            row = QHBoxLayout()
            row.addWidget(QLabel(caption))
            bar = QProgressBar()
            bar.setFixedHeight(6)
            bar.setTextVisible(False)
            self.bars[key] = bar
            row.addWidget(bar, 1)
            outer.addLayout(row)
        actions = QHBoxLayout()
        for caption, callback in [('摸摸', pet.pat), ('投喂', lambda: self.page('food')),
                                  ('音乐', lambda: self.page('music')), ('休息', lambda: self.page('rest')),
                                  ('设置', lambda: self.page('settings'))]:
            button = QPushButton(caption)
            button.clicked.connect(callback)
            actions.addWidget(button)
        outer.addLayout(actions)
        self.content = QVBoxLayout()
        self.content.setSpacing(7)
        outer.addLayout(self.content)
        self.mode = 'home'
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.auto_close)

    def auto_close(self):
        if self.underMouse():
            self.close_timer.start(8000)
        else:
            self.hide()

    def refresh(self):
        data = self.pet.panel.store.pet()
        self.name.setText(f"{self.pet.character_name}  Lv.{data['level']}     音符 {data['notes']}")
        self.bars['xp'].setRange(0, 50 + 20 * (data['level'] - 1))
        self.bars['xp'].setValue(data['xp'])
        for key in ('hunger', 'mood'):
            self.bars[key].setRange(0, 100)
            self.bars[key].setValue(data[key])
            self.bars[key].setToolTip(str(data[key]) + '/100')

    def page(self, name='home'):
        self.mode = name
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if name == 'food':
            for food, (cost, *_rest) in FOODS.items():
                button = QPushButton(f'{food}     {cost} 音符')
                button.clicked.connect(lambda checked=False, value=food: self.pet.panel.feed(value))
                self.content.addWidget(button)
        elif name == 'music':
            title = self.pet.panel.song_title.text()
            self.music_title = QLabel(title)
            self.music_title.setWordWrap(True)
            self.music_title.setTextFormat(Qt.TextFormat.PlainText)
            self.content.addWidget(self.music_title)
            self.add_button('上一首', lambda: self.pet.panel.step(-1))
            self.add_button('播放 / 暂停', self.pet.panel.toggle)
            self.add_button('下一首', lambda: self.pet.panel.step(1))
            self.add_button('拿麦克风唱歌 / 收麦', self.pet.toggle_singing)
            self.add_button('拿麦克风转个身', self.pet.turn_body)
            self.add_button('打开歌单 / 添加 MP3', lambda: self.pet.open_tools(0))
            self.add_button('B站网页歌单 / 添加链接', lambda: self.pet.open_tools(3))
        elif name == 'rest':
            self.add_button('盖被子睡觉', self.pet.toggle_sleep)
            self.add_button('熬夜玩手机', self.pet.toggle_phone)
            self.add_button('起床 / 收手机', self.pet.wake_up)
        elif name == 'settings':
            startup = QCheckBox('开机自启')
            try:
                startup.setChecked(self.pet.panel.startup.enabled())
                startup.setEnabled(self.pet.panel.startup.supported)
            except OSError:
                startup.setEnabled(False)
            startup.toggled.connect(self.pet.panel.toggle_startup)
            startup.toggled.connect(lambda: self.page('settings'))
            self.content.addWidget(startup)
            passthrough = QCheckBox('鼠标穿透（可从系统托盘关闭）')
            passthrough.setChecked(self.pet.mouse_passthrough)
            passthrough.toggled.connect(self.pet.set_mouse_passthrough)
            self.content.addWidget(passthrough)
            self.content.addWidget(QLabel('桌宠大小'))
            scale = QSlider(Qt.Orientation.Horizontal)
            scale.setRange(75, 150)
            scale.setValue(round(self.pet.scale * 100))
            scale.valueChanged.connect(lambda value: self.pet.set_scale(value / 100))
            self.content.addWidget(scale)
            self.add_button('更多设置', lambda: self.pet.open_tools(2))
            self.add_button('聊天 API 设置', lambda: self.pet.open_chat(settings=True))
            self.add_button('扩展功能 / Mod', self.pet.open_mods)
        else:
            hint = QLabel('点头部摸摸 · 拖动提起 · 双击/右键菜单')
            hint.setObjectName('Muted')
            self.content.addWidget(hint)
            self.add_button('一起加油吧', lambda: self.pet.reply())
            self.add_button('和我聊天', self.pet.open_chat)
        self.refresh()
        self.adjustSize()
        if self.isVisible():
            clamp_near(self.pet, self)

    def add_button(self, caption, callback):
        button = QPushButton(caption)
        button.clicked.connect(callback)
        self.content.addWidget(button)

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.pet.reveal_dock()
            self.pet.bubble.hide()
            self.page('home')
            clamp_near(self.pet, self)
            self.show()
            self.close_timer.start(12000)


class DesktopPet(QWidget):
    @property
    def playing(self):
        return self.behavior.playing

    @playing.setter
    def playing(self, value):
        self.behavior.playing = bool(value)

    @property
    def sleeping(self):
        return self.behavior.mode == 'sleep'

    @property
    def using_phone(self):
        return self.behavior.mode == 'phone'

    @property
    def action(self):
        return self.behavior.action

    def __init__(self, panel_factory):
        super().__init__()
        self.setWindowTitle('洛天依桌宠')
        self.setWindowIcon(application_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.behavior = PetBehavior()
        self.last_interaction = time.monotonic()
        self.press_point = None
        self.dock_press = False
        self.mouse_passthrough = False
        self.drag_offset = None
        self.dragging = False
        self.drag_dock_edge = ''
        self.drag_sway = DragSway()
        self.drag_anchor = QPointF(130, 82)
        self.drag_sample_point = None
        self.drag_sample_time = 0.0
        self.pointer_follow = PointerFollow()
        self.mouse_interactions = MouseInteractions()
        self.dock_edge = ''
        self.dock_reveal = 1.0
        self.dock_target = 1.0
        self.last_frame_time = time.monotonic()
        self.fold_timer = QTimer(self)
        self.fold_timer.setSingleShot(True)
        self.fold_timer.timeout.connect(self.fold_dock)
        self.last_pat = 0
        self.frames = {}
        self.pixmap_cache = {}
        self.scaled_frames = {}
        self.frame_masks = {}
        self.hit_region = QRegion()
        self.phase = 0
        self.character_name = '洛天依'
        self.character_pack = None
        self.live2d_renderer = None
        self.live2d_frame_key = None
        self.live2d_pixmap = None
        self.anchors = dict(DEFAULT_ANCHORS)
        self.head_region = QRegion()
        self.panel = panel_factory(self)
        self.panel.songChanged.connect(self.refresh_music_title)
        self.behavior.set_mode(self.panel.settings.value('activity_mode', 'idle')
                               if self.panel.settings.value('activity_mode', 'idle') in MODES else 'idle')
        self.variant = preferred_variant(self.panel.settings)
        self.scale = float(self.panel.settings.value('pet_scale', 1.0))
        self.bubble = Bubble(self)
        self.toolbar = PetToolbar(self)
        self.effects = PetEffects(self)
        self.set_scale(self.scale)
        if not self.set_variant(self.variant):
            failure = self.panel.character_note.text()
            self.set_variant('refined')
            self.panel.character_note.setText('已恢复内置洛天依。' + failure)
        self.panel.settings.setValue('appearance_revision', APPEARANCE_REVISION)
        self.panel.settings.sync()
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.touch)
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.begin_drag)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        menu.setStyleSheet(CONTROL_STYLE)
        menu.addAction('显示桌宠', self.restore)
        menu.addAction('互动菜单', self.toolbar.toggle)
        menu.addAction('歌单', lambda: self.open_tools(0))
        menu.addAction('网易云 / 歌词与节拍', lambda: self.open_music_companion(0))
        menu.addAction('聊天', self.open_chat)
        menu.addAction('扩展功能 / Mod', self.open_mods)
        menu.addAction('设置', lambda: self.open_tools(2))
        menu.addAction('显示 B站播放网页', lambda: self.panel.bilibili.send({'cmd': 'show'})
                       if self.panel.bilibili.active else self.open_tools(3))
        menu.addAction('B站网页最小化到托盘', lambda: self.panel.bilibili.send({'cmd': 'hide'}))
        self.passthrough_action = menu.addAction('鼠标穿透')
        self.passthrough_action.setCheckable(True)
        self.passthrough_action.toggled.connect(self.set_mouse_passthrough)
        menu.addAction('关闭鼠标穿透并找回角色', self.recover_input)
        menu.addAction('退出', QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('洛天依 · 右键打开菜单')
        self.tray.show()
        self.restore()
        self.set_mouse_passthrough(self.panel.settings.value('mouse_passthrough', False, type=bool))

    def set_mouse_passthrough(self, enabled):
        enabled = bool(enabled)
        self.mouse_passthrough = enabled
        self.panel.settings.setValue('mouse_passthrough', enabled)
        for control in (self.panel.passthrough_toggle, self.passthrough_action):
            control.blockSignals(True)
            control.setChecked(enabled)
            control.blockSignals(False)
        if enabled:
            self.hold_timer.stop()
            self.click_timer.stop()
            self.press_point = None
            if self.dragging:
                self.behavior.end_drag(landing=False)
            self.dragging = False
            self.drag_dock_edge = ''
            self.toolbar.hide()
            self.bubble.hide()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        flag = Qt.WindowType.WindowTransparentForInput
        if bool(self.windowFlags() & flag) != enabled:
            visible, position = self.isVisible(), self.pos()
            self.setWindowFlag(flag, enabled)
            self.move(position)
            if visible:
                self.show()
        self.tray.setToolTip(self.character_name + (' · 鼠标穿透中，右键托盘可关闭' if enabled else ' · 右键打开菜单'))

    def recover_input(self):
        self.set_mouse_passthrough(False)
        self.restore()
        self.reveal_dock()
        self.bubble.say('鼠标穿透已关闭，可以继续拖动和互动。')

    def refresh_music_title(self, *_):
        if self.toolbar.isVisible() and self.toolbar.mode == 'music':
            title = self.panel.song_title.text()
            if title != self.toolbar.music_title.text():
                self.toolbar.music_title.setText(title)
                self.toolbar.adjustSize()
                clamp_near(self, self.toolbar)

    def set_variant(self, variant):
        # Decode and validate completely before touching the displayed character.
        pack = None
        renderer = None
        try:
            if variant in ('refined', 'simple', 'live2d'):
                sources = builtin_sources('refined' if variant == 'live2d' else variant)
                frames = {}
                for state, path in sources.items():
                    cache_key = str(path)
                    if cache_key not in self.pixmap_cache:
                        pixmap = QPixmap(cache_key)
                        if not pixmap.isNull():
                            self.pixmap_cache[cache_key] = pixmap.copy(sprite_bounds(pixmap))
                    if cache_key in self.pixmap_cache:
                        frames[state] = self.pixmap_cache[cache_key]
                if variant == 'live2d':
                    from live2d_renderer import Live2DRenderer
                    # Load completely before replacing the last successful renderer.
                    renderer = self.live2d_renderer or Live2DRenderer()
                    first_frame = renderer.frame('idle', 0)
                    if first_frame.isNull():
                        raise RuntimeError('Live2D 没有生成有效画面')
            else:
                pack = read_pack(selected_folder(self.panel.characters_dir, variant))
                images = validate_images(pack)
                loaded = {path: QPixmap.fromImage(images[state]) for state, path in pack.states.items()}
                sources = {state: pack.state_path(state) for state in STATES}
                # Keep the common canvas: independent cropping destroys pose alignment.
                frames = {state: loaded[path] for state, path in sources.items()}
            if 'idle' not in frames or frames['idle'].isNull():
                raise ValueError('角色缺少可显示的 idle 素材')
        except (ValueError, OSError, RuntimeError, ImportError) as error:
            if renderer is not None and renderer is not self.live2d_renderer:
                renderer.close()
            self.panel.character_note.setText('角色加载失败，保留当前角色：' + str(error))
            self.panel.appearance.blockSignals(True)
            self.panel.appearance.setCurrentIndex(self.panel.appearance.findData(getattr(self, 'variant', 'refined')))
            self.panel.appearance.blockSignals(False)
            return False
        if self.live2d_renderer is not None and renderer is not self.live2d_renderer:
            self.live2d_renderer.close()
        self.live2d_renderer = renderer
        self.live2d_frame_key = None
        self.live2d_pixmap = None
        self.character_pack, self.frames, self.variant = pack, frames, variant
        self.character_name = pack.name if pack else '洛天依'
        self.anchors = dict(pack.anchors) if pack else dict(DEFAULT_ANCHORS)
        filename = sources['idle']
        self.sprite = self.frames.get('idle', QPixmap())
        self.prepare_frames()
        update_cover(self.panel, filename, self.sprite)
        self.panel.settings.setValue('character_selection', variant)
        if pack is None and variant != 'live2d':
            self.panel.settings.setValue('visual_variant', variant)
        self.panel.settings.sync()
        self.panel.appearance.blockSignals(True)
        if self.panel.appearance.findData(variant) < 0:
            self.panel.appearance.addItem(self.character_name + ' · 自定义', variant)
        self.panel.appearance.setCurrentIndex(self.panel.appearance.findData(variant))
        self.panel.appearance.blockSignals(False)
        self.panel.pointer_toggle.setEnabled(renderer is not None)
        self.panel.interactions_toggle.setEnabled(renderer is not None)
        self.panel.character_note.setText(
            f'当前：{pack.name}；作者：{pack.author or "未填写"}。来源与授权：{pack.source or "请自行确认"}'
            if pack else '当前使用 Live2D 洛天依；睡姿按头部尺度放大，拖动后恢复原状态。'
            if renderer else '当前使用内置洛天依。添加角色后点击“刷新角色”。')
        self.setWindowTitle(self.character_name + ' · 桌宠')
        self.panel.setWindowTitle(self.character_name + ' · 歌单与设置')
        if hasattr(self, 'tray'):
            self.tray.setToolTip(self.character_name + (' · 鼠标穿透中，右键托盘可关闭' if self.mouse_passthrough else ' · 右键打开菜单'))
        self.toolbar.refresh()
        if getattr(self, 'chat_window', None) is not None:
            self.chat_window.sync_character()
        self.head_region = self.hit_region = QRegion()
        self.update()
        return True

    def refresh_characters(self, reload_current=False):
        try:
            packs, errors = discover_packs(self.panel.characters_dir)
        except OSError as error:
            self.panel.character_note.setText('角色目录无法读取：' + str(error))
            return
        choice = self.panel.appearance
        choice.blockSignals(True)
        choice.clear()
        for caption, variant in BUILTIN_APPEARANCES:
            choice.addItem(caption, variant)
        for selection, pack in packs.items():
            choice.addItem(pack.name + ' · ' + pack.root.name, selection)
        if choice.findData(self.variant) < 0:
            choice.addItem(self.character_name + '（当前已加载，文件夹不可用）', self.variant)
        choice.setCurrentIndex(choice.findData(self.variant))
        choice.blockSignals(False)
        if reload_current:
            self.set_variant(self.variant)
        result = f'找到 {len(packs)} 个自定义角色。目录：{self.panel.characters_dir}'
        if self.character_pack and not reload_current:
            pack = self.character_pack
            result += f'\n当前：{pack.name}；作者：{pack.author or "未填写"}。来源与授权：{pack.source or "请自行确认"}'
        if errors:
            result += '\n未载入：' + '\n'.join(errors[:8])
        if not reload_current or errors:
            self.panel.character_note.setText(result + ('\n' + self.panel.character_note.text() if reload_current else ''))

    def open_character_folder(self):
        try:
            self.panel.characters_dir.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.panel.characters_dir.resolve()))):
                raise OSError('系统未能打开文件夹')
        except OSError as error:
            self.panel.character_note.setText('打开失败：' + str(error) + '\n目录：' + str(self.panel.characters_dir))

    def set_scale(self, scale):
        anchor = self.frameGeometry().bottomLeft() if self.isVisible() else None
        self.scale = max(0.75, min(1.5, scale))
        self.resize(round(260 * self.scale), round(310 * self.scale))
        if anchor is not None:
            bounds = (QApplication.screenAt(anchor) or QApplication.primaryScreen()).availableGeometry()
            self.move(max(bounds.left(), min(anchor.x(), bounds.right() - self.width())),
                      max(bounds.top(), min(anchor.y() - self.height(), bounds.bottom() - self.height())))
        self.panel.settings.setValue('pet_scale', self.scale)
        self.prepare_frames()
        if self.dock_edge:
            self.move(dock_position(self.pos(), self.size(), self.screen_bounds(), self.dock_edge))
            self.save_position()
        self.update()

    def close_live2d(self):
        if self.live2d_renderer is not None:
            self.live2d_renderer.close()
            self.live2d_renderer = None

    def update_live2d_geometry(self, activity):
        # The same-sized person lying down needs a wider window, not a smaller head.
        base_width = 400 if activity == 'sleep' else 320 if activity == 'phone' else 260
        width, height = round(base_width * self.scale), round(310 * self.scale)
        if self.size().width() == width and self.height() == height:
            return
        previous_position = self.pos()
        center, bottom = self.x() + self.width() / 2, self.y() + self.height()
        self.resize(width, height)
        self.move(clamp_position(QPoint(round(center - width / 2), bottom - height),
                                 self.size(), self.screen_bounds()))
        if self.dock_edge:
            self.move(dock_position(self.pos(), self.size(), self.screen_bounds(), self.dock_edge))
        if self.dragging and self.drag_offset is not None:
            self.drag_offset += previous_position - self.pos()
            self.drag_anchor += QPointF(previous_position - self.pos())

    def interaction_transform(self, activity):
        transform = QTransform()
        if activity not in ('lift', 'land') or self.dock_edge:
            return transform
        anchor = self.drag_anchor if activity == 'lift' else QPointF(self.width() / 2, 280 * self.scale)
        angle, sx, sy = interaction_pose(activity, self.behavior.activity_elapsed, self.drag_sway.angle)
        transform.translate(anchor.x(), anchor.y())
        transform.rotate(angle)
        transform.scale(sx, sy)
        transform.translate(-anchor.x(), -anchor.y())
        return transform

    def paint_live2d(self, painter, activity):
        from live2d_renderer import POSE_SCALE
        from music_tools.clock import beat_values
        elapsed = self.behavior.activity_elapsed
        beat = self.current_music_beat(activity)
        key = (activity, round(elapsed * 30), beat_values(beat), *(round(v, 3) for v in self.live2d_renderer.pointer))
        try:
            if self.live2d_frame_key != key:
                image = self.live2d_renderer.frame(activity, elapsed, beat)
                self.live2d_pixmap = QPixmap.fromImage(image)
                self.live2d_frame_key = key
            pixmap = self.live2d_pixmap
        except Exception as error:
            self.panel.character_note.setText('Live2D 渲染失败，已恢复精致版：' + str(error))
            QTimer.singleShot(0, lambda: self.set_variant('refined'))
            return
        transform = QTransform()
        transform.translate(self.width() / 2, 280 * self.scale)
        factor = .5 * self.scale * POSE_SCALE.get(activity, 1)
        transform.scale(factor, factor)
        transform.translate(-192, -560)
        if activity not in ('sleep', 'phone'):
            transform *= self.dock_transform()
        transform *= self.interaction_transform(activity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setTransform(transform)
        painter.drawPixmap(0, 0, pixmap)
        painter.resetTransform()
        self.hit_region = transform.map(QRegion(pixmap.mask())).intersected(QRegion(self.rect()))
        head = (QRect(42, 405, 118, 140) if activity == 'sleep' else
                QRect(13, 384, 166, 163) if activity == 'phone' else QRect(75, 15, 230, 220))
        self.head_region = transform.map(QRegion(head, QRegion.RegionType.Ellipse))

    def prepare_frames(self):
        max_width, max_height = 236 * self.scale, 270 * self.scale
        if self.character_pack:
            feet_x, feet_y = self.anchors['feet']
            max_width = min(max_width, self.width() / (2 * max(feet_x, 1 - feet_x)))
            if feet_y > 0:
                max_height = min(max_height, 280 * self.scale / feet_y)
            if feet_y < 1:
                max_height = min(max_height, (self.height() - 280 * self.scale) / (1 - feet_y))
        self.scaled_frames = {
            name: pixmap.scaled(max(1, round(max_width)), max(1, round(154 * self.scale if self.character_pack is None and name in ('sleep', 'phone') else max_height)),
                                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            for name, pixmap in self.frames.items()
        }
        self.frame_masks = {name: QRegion(pixmap.mask()) for name, pixmap in self.scaled_frames.items()}
        self.singing_rigs = {name: SingingRig(pixmap, self.frame_masks[name])
                             for name, pixmap in self.scaled_frames.items()
                             if self.character_pack is None and name.startswith('sing-')}

    def restore(self):
        screen = QApplication.primaryScreen().availableGeometry()
        saved = self.panel.settings.value('position')
        point = saved if isinstance(saved, QPoint) else QPoint(screen.right() - self.width() - 40, screen.bottom() - self.height() - 20)
        if not any(s.availableGeometry().contains(point) for s in QApplication.screens()):
            point = screen.topLeft() + QPoint(60, 120)
        self.move(point)
        edge = self.panel.settings.value('dock_edge', '')
        self.dock_edge = edge if edge in EDGES else ''
        self.dock_reveal = self.dock_target = 0.0 if self.dock_edge else 1.0
        if self.dock_edge:
            self.move(dock_position(self.pos(), self.size(), self.screen_bounds(), self.dock_edge))
        self.show()

    def screen_bounds(self):
        return (QApplication.screenAt(self.frameGeometry().center()) or
                QApplication.primaryScreen()).availableGeometry()

    def save_position(self):
        self.panel.settings.setValue('position', self.pos())
        self.panel.settings.setValue('dock_edge', self.dock_edge)

    def snap_to_edge(self):
        bounds = self.screen_bounds()
        self.dock_edge = nearest_edge(self.pos(), self.size(), bounds, round(32 * self.scale))
        if self.dock_edge:
            self.move(dock_position(self.pos(), self.size(), bounds, self.dock_edge))
            self.fold_timer.start(900)
        else:
            self.dock_reveal = self.dock_target = 1.0
        self.save_position()

    def reveal_dock(self):
        if self.drag_dock_edge:
            return
        self.fold_timer.stop()
        self.dock_target = 1.0

    def fold_dock(self):
        if getattr(self, 'chat_window', None) is not None and self.chat_window.isVisible():
            return
        host = getattr(self, 'mod_host', None)
        if host and host.window is not None and host.window.isVisible():
            return
        music = getattr(self, 'music_companion', None)
        if music and music.window is not None and music.window.isVisible():
            return
        if not self.dock_edge or self.dragging:
            return
        if (self.sleeping or self.using_phone or self.press_point is not None or self.toolbar.isVisible() or self.panel.isVisible() or
                self.bubble.isVisible() or self.behavior.layers):
            self.fold_timer.start(700)
            return
        self.dock_target = 0.0

    def enterEvent(self, event):
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.dock_edge:
            self.fold_timer.start(900)
        super().leaveEvent(event)

    def character_head(self):
        if self.live2d_renderer is not None:
            return QPointF(self.width() / 2, 82 * self.scale)
        image = self.scaled_frames.get('idle')
        if self.character_pack and image is not None:
            return QPointF(self.width() / 2 + (self.anchors['head'][0] - self.anchors['feet'][0]) * image.width(),
                           280 * self.scale + (self.anchors['head'][1] - self.anchors['feet'][1]) * image.height())
        return QPointF(self.width() / 2, 93 * self.scale)

    def dock_transform(self):
        transform = QTransform()
        if not self.dock_edge:
            return transform
        amount = 1.0 - self.dock_reveal
        head = self.character_head()
        targets = {
            'left': (QPointF(22 * self.scale, self.height() / 2), 90),
            'right': (QPointF(self.width() - 22 * self.scale, self.height() / 2), -90),
            'top': (QPointF(self.width() / 2, 25 * self.scale), 180),
            'bottom': (QPointF(self.width() / 2, self.height() - 25 * self.scale), 0),
        }
        target, angle = targets[self.dock_edge]
        transform.translate(head.x() + (target.x() - head.x()) * amount,
                            head.y() + (target.y() - head.y()) * amount)
        transform.rotate(angle * amount)
        transform.translate(-head.x(), -head.y())
        return transform

    def open_tools(self, tab=0):
        self.reveal_dock()
        self.panel.tabs.setCurrentIndex(tab)
        clamp_near(self, self.panel)
        self.panel.show()
        self.panel.raise_()
        self.toolbar.hide()

    def react(self, action, seconds=1.7, words=None):
        self.behavior.react(action, seconds)
        if self.dragging:
            return
        self.reveal_dock()
        if self.dock_edge:
            self.fold_timer.start(round((seconds + 3.5) * 1000))
        self.last_interaction = time.monotonic()
        if words:
            self.bubble.say(words)
        self.update()

    def pat(self):
        if self.behavior.has_action('eat'):
            return
        self.toolbar.hide()
        now = time.monotonic()
        if now - self.last_pat >= 60:
            self.panel.store.interact()
            self.last_pat = now
            self.panel.refresh_growth()
        self.react('happy', words=random.choice(['嘿嘿，头发要被摸乱啦。', '有你在，今天也很开心！', '再陪我听一首吧？']))

    def touch(self):
        self.toolbar.hide()
        if self.using_phone:
            self.set_mode('idle')
            self.react('happy', words='被发现啦，这就收手机！')
        elif self.sleeping:
            self.set_mode('idle')
            self.react('happy', words='醒啦！要一起听歌吗？')
        elif getattr(self, 'touch_head', True):
            self.pat()
        else:
            self.react('poke', 1.0, '欸？是在叫我吗？')

    def open_music_companion(self, page=0):
        companion = getattr(self, 'music_companion', None)
        if companion is None:
            self.bubble.say(getattr(self, 'music_startup_error', '') or '歌词与节拍暂时无法使用，请重新启动桌宠。')
            return
        try:
            companion.open(page)
        except Exception as error:
            self.bubble.say('音乐工具暂时无法打开：' + str(error))

    def current_music_beat(self, activity):
        companion = getattr(self, 'music_companion', None)
        return companion.beat if companion and activity == 'sing' and not self.behavior.layers else None

    def open_mods(self, checked=False):
        host = getattr(self, 'mod_host', None)
        if host is None:
            self.bubble.say(getattr(self, 'mod_startup_error', '') or '扩展功能暂时不可用，请重启桌宠后再试。')
            return
        try:
            host.open()
        except Exception:
            self.bubble.say('扩展页面暂时无法打开，桌宠和音乐仍可正常使用。')

    def open_chat(self, checked=False, settings=False):
        if getattr(self, 'chat_window', None) is None:
            from pet_chat.window import ChatWindow
            try:
                self.chat_window = ChatWindow(self)
            except (OSError, sqlite3.Error):
                self.bubble.say('聊天数据无法打开，请检查磁盘空间和数据目录权限。')
                return
        self.chat_window.show_chat(settings=settings)

    def reply(self):
        self.toolbar.hide()
        self.react('happy', words=random.choice(['一起加油！我会陪着你的。', '累了就歇一会儿，我在这里。', '今天也有好多好听的歌呢。']))

    def toggle_sleep(self):
        if self.sleeping:
            self.wake_up()
        else:
            self.set_mode('sleep')
            self.reveal_dock()
            self.toolbar.hide()
            self.bubble.say('被子盖好啦……晚安。点我就能叫醒我。')
            self.update()

    def toggle_phone(self):
        if self.using_phone:
            self.wake_up()
            return
        self.set_mode('phone')
        self.reveal_dock()
        self.toolbar.hide()
        self.bubble.say('再看一小会儿……就一小会儿。')
        self.update()

    def wake_up(self):
        self.toolbar.hide()
        self.set_mode('idle')
        self.react('happy', words='起来啦，继续陪你！')

    def set_mode(self, mode):
        self.behavior.set_mode(mode)
        self.panel.settings.setValue('activity_mode', mode)
        self.update()

    def toggle_singing(self):
        self.toolbar.hide()
        self.set_mode(('listen' if self.playing else 'idle') if self.behavior.mode == 'sing' else 'sing')
        self.reveal_dock()
        self.bubble.say('一起唱起来！' if self.behavior.mode == 'sing' else '麦克风先收好啦。')

    def turn_body(self):
        self.toolbar.hide()
        self.react('turn', 4.8, '换个角度，唱给你听。')

    def feed_reaction(self, success, words):
        if success:
            self.toolbar.hide()
            self.react('eat', 2.8, '啊呜……好吃！')
            self.toolbar.refresh()
        else:
            self.bubble.say(words)

    def begin_drag(self):
        if self.press_point is None or self.dragging:
            return
        self.hold_timer.stop()
        was_docked = bool(self.dock_edge)
        self.dragging = True
        self.drag_dock_edge = ''
        self.click_timer.stop()
        self.fold_timer.stop()
        self.dock_edge = ''
        self.dock_reveal = self.dock_target = 1.0
        if was_docked:
            # Keep the head close to the held pointer as it unfolds from the edge.
            desired = self.press_point - self.character_head().toPoint()
            self.move(clamp_position(desired, self.size(), self.screen_bounds()))
            self.drag_offset = self.press_point - self.pos()
        self.behavior.begin_drag()
        self.drag_anchor = QPointF(self.press_point - self.pos())
        self.drag_sample_point = QPoint(self.press_point)
        self.drag_sample_time = time.monotonic()
        self.drag_sway.start()
        self.toolbar.hide()
        self.bubble.hide()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def animate(self):
        now = time.monotonic()
        delta = min(0.1, max(0, now - self.last_frame_time))
        self.last_frame_time = now
        if self.dock_reveal != self.dock_target:
            step = delta / 0.24
            difference = self.dock_target - self.dock_reveal
            self.dock_reveal += max(-step, min(step, difference))
        if (self.dock_edge and self.dock_target == 1.0 and not self.dragging and
                not self.fold_timer.isActive()):
            self.fold_timer.start(900)
        self.phase = now
        self.drag_sway.step(delta)
        self.behavior.tick(delta)
        if self.live2d_renderer is not None:
            activity = 'idle' if self.drag_dock_edge else self.behavior.activity
            self.update_live2d_geometry(activity)
            global_pointer = QCursor.pos()
            pointer = self.mapFromGlobal(global_pointer)
            head = self.character_head()
            enabled = (self.panel.pointer_toggle.isChecked() and not self.dragging
                       and not self.dock_edge and self.press_point is None
                       and not self.panel.isVisible() and not self.toolbar.isVisible()
                       and activity not in ('sleep', 'phone', 'lift', 'land'))
            self.live2d_renderer.pointer = self.pointer_follow.step(
                pointer.x()-head.x(), pointer.y()-head.y(), delta,
                enabled=enabled, scale=self.scale)
            local = pointer
            in_head = self.head_region.contains(local)
            # The free singing hand is extended; natural hands are lower. Keep
            # the dwell target with the visible pose rather than over a thigh.
            hands = (((self.width()/2-62*self.scale, 185*self.scale),)
                     if activity in ('sing', 'turn') else
                     tuple((self.width()/2+side*46*self.scale, 213*self.scale)
                           for side in (-1, 1)))
            near_hand = any(math.hypot(local.x()-x, local.y()-y) < 27*self.scale
                            for x, y in hands) and not in_head
            reaction = self.mouse_interactions.step(
                global_pointer.x(), global_pointer.y(), delta,
                in_head=in_head, near_hand=near_hand, scale=self.scale,
                enabled=(self.panel.interactions_toggle.isChecked() and not self.mouse_passthrough
                         and not self.dragging and not self.dock_edge and self.press_point is None
                         and not self.click_timer.isActive() and not self.hold_timer.isActive()
                         and not self.behavior.layers and not self.sleeping and not self.using_phone
                         and not self.panel.isVisible() and not self.toolbar.isVisible()
                         and not self.hit_region.isEmpty()))
            if reaction:
                self.react(reaction, REACTION_SECONDS[reaction])
        elif self.width() != round(260 * self.scale):
            self.resize(round(260 * self.scale), round(310 * self.scale))
        self.update()
        self.effects.sync()

    def paintEvent(self, event):
        # Replace the backing buffer, including pixels occupied by the previous pose.
        # Changing a native window mask each frame can leave stale layered-window pixels.
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        now = self.phase or time.monotonic()
        elapsed = self.behavior.elapsed
        activity = 'idle' if self.drag_dock_edge else self.behavior.activity
        if self.live2d_renderer is not None:
            self.paint_live2d(painter, activity)
            painter.end()
            return
        state = 'idle'
        angle, y, sx, sy = 0.0, 0.0, 1.0, 1.0
        if activity == 'lift':
            state = 'lift'
        elif activity == 'eat':
            state, y = 'eat', math.sin(elapsed * 13) * 1.5
            sx = 1 + math.sin(elapsed * 13) * 0.008
        elif activity in ('happy', 'poke', 'head_rub', 'mouse_wave'):
            state = 'lift' if activity == 'poke' else 'happy'
            angle = math.sin(elapsed * 11) * (2 if activity == 'happy' else 4)
            y = -abs(math.sin(elapsed * 7)) * 7
        elif activity == 'land':
            pass  # Shared pickup/drop transform below also covers PNG models.
        elif activity == 'sleep':
            state = 'sleep' if 'sleep' in self.scaled_frames else 'blink'
            sy = 1 + math.sin(now * 1.5) * 0.008
        elif activity == 'phone':
            state = 'phone' if 'phone' in self.scaled_frames else 'idle'
            sy = 1 + math.sin(now * 1.8) * 0.004
            angle = math.sin(now * 2.5) * 0.3
            y = -max(0, math.sin(now * 4.5)) * 0.7
        elif activity in ('sing', 'turn'):
            motion_time = elapsed if activity == 'turn' else now
            state, residual = singing_pose(motion_time)
            sx = 1 - abs(residual) * 0.035
            angle, y = math.sin(motion_time * 3.5) * 1.4, -abs(math.sin(motion_time * 3.5)) * 2
            from music_tools.clock import beat_values
            values = beat_values(self.current_music_beat(activity))
            if values is not None:
                index, phase = values
                pulse = math.sin(math.pi * phase) ** 2
                angle, y = (1 if index % 2 else -1) * pulse * 1.4, -pulse * 2
        else:
            state = 'blink' if now % 4.8 < 0.15 else 'idle'
            sy = 1 + math.sin(now * 2) * 0.003
        key = state if state in self.scaled_frames else 'idle'
        image = self.scaled_frames.get(key)
        if image is None or image.isNull():
            painter.end()
            return
        scale = self.scale
        transform = QTransform()
        transform.translate(self.width() / 2, 280 * scale + y * scale)
        transform.rotate(angle)
        transform.scale(sx, sy)
        transform.translate(-image.width() * (self.anchors['feet'][0] if self.character_pack else .5),
                            -image.height() * (self.anchors['feet'][1] if self.character_pack else 1))
        resting = key in ('sleep', 'phone')
        if not resting:
            transform *= self.dock_transform()
        transform *= self.interaction_transform(activity)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setTransform(transform)
        local_mask = self.frame_masks[key]
        if key in self.singing_rigs:
            local_mask = self.singing_rigs[key].draw(painter, motion_time, scale, self.current_music_beat(activity))
        else:
            painter.drawPixmap(0, 0, image)
        if key == 'phone' and self.character_pack is None:
            # A gentle screen-light pulse and small tap ring, clipped to the sprite.
            painter.save()
            painter.setClipRegion(self.frame_masks[key])
            pulse = (math.sin(now * 2.4) + 1) / 2
            painter.setBrush(QColor(130, 207, 255, round(10 + pulse * 17)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(image.width() * 0.28, image.height() * 0.73),
                                image.width() * 0.07, image.height() * 0.13)
            tap = (now * 0.65) % 1
            painter.setPen(QPen(QColor(192, 235, 255, round((1 - tap) * 110)), 0.8 * scale))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(image.width() * 0.29, image.height() * 0.79),
                                (1 + tap * 4) * scale, (1 + tap * 4) * scale)
            painter.restore()
        painter.resetTransform()
        mask = transform.map(local_mask)
        if self.character_pack:
            head_x, head_y = self.anchors['head']
            head_box = QRect(round((head_x - .24) * image.width()), round((head_y - .2) * image.height()),
                             round(.48 * image.width()), round(.4 * image.height()))
            self.head_region = transform.map(QRegion(head_box, QRegion.RegionType.Ellipse))
        painter.end()
        self.hit_region = mask.intersected(QRegion(self.rect()))
        # Windows' layered window uses the rendered alpha for click-through.
        # Keep a single rectangular backing surface instead of changing native masks.

    def mousePressEvent(self, event):
        if self.mouse_passthrough:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.hit_region.contains(event.position().toPoint()):
                event.ignore()
                return
            self.dock_press = bool(self.dock_edge)
            if not self.dock_press:
                self.reveal_dock()
            self.press_point = event.globalPosition().toPoint()
            self.drag_offset = self.press_point - self.pos()
            self.touch_head = (bool(self.dock_edge and self.dock_reveal < 0.9) or
                               (self.head_region.contains(event.position().toPoint()) if self.character_pack or self.live2d_renderer
                                else event.position().y() < self.height() * 0.57))
            if not self.dock_press:
                self.hold_timer.start(280)

    def mouseMoveEvent(self, event):
        if self.mouse_passthrough or self.press_point is None:
            return
        point = event.globalPosition().toPoint()
        if not self.dragging and (point - self.press_point).manhattanLength() > 8:
            self.begin_drag()
        if self.dragging:
            self.drag_to(point)

    def drag_to(self, point):
        now = time.monotonic()
        if self.drag_sample_point is not None:
            self.drag_sway.move(point.x() - self.drag_sample_point.x(),
                                now - self.drag_sample_time, self.scale)
        self.drag_sample_point, self.drag_sample_time = QPoint(point), now
        desired = point - self.drag_offset
        if self.drag_dock_edge:
            bounds = self.screen_bounds()
            if edge_gap(desired, self.size(), bounds, self.drag_dock_edge) < round(12 * self.scale):
                self.move(dock_position(desired, self.size(), bounds, self.drag_dock_edge))
                return
            # Pull back into the desktop during the same held gesture to detach.
            self.drag_dock_edge = self.dock_edge = ''
            self.dock_reveal = self.dock_target = 1.0
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        self.move(clamp_position(desired, self.size(), bounds))
        edge = pushed_edge(desired, self.size(), bounds, round(24 * self.scale))
        if edge:
            self.drag_dock_edge = self.dock_edge = edge
            self.fold_timer.stop()
            self.dock_target = 0.0
            self.move(dock_position(self.pos(), self.size(), bounds, edge))
            self.save_position()
        self.update()

    def mouseReleaseEvent(self, event):
        self.hold_timer.stop()
        if self.mouse_passthrough:
            event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        had_press = self.press_point is not None
        self.press_point = None
        if getattr(self, 'ignore_release', False):
            self.ignore_release = False
            return
        if not had_press and not self.dragging:
            return
        if self.dragging:
            self.dragging = False
            self.drag_sway.release()
            if self.drag_dock_edge:
                self.drag_dock_edge = ''
                self.behavior.end_drag(landing=False)
                self.dock_target = 0.0
                self.save_position()
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()
                return
            self.behavior.end_drag()
            self.snap_to_edge()
        elif not self.dock_press:
            self.click_timer.start(220)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        if self.mouse_passthrough:
            event.ignore()
            return
        self.click_timer.stop()
        self.ignore_release = True
        self.toolbar.toggle()

    def contextMenuEvent(self, event):
        if self.mouse_passthrough:
            event.ignore()
            return
        self.toolbar.toggle()

    def hideEvent(self, event):
        self.toolbar.hide()
        self.bubble.hide()
        if hasattr(self, 'effects'):
            self.effects.hide()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'effects'):
            self.effects.sync()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'effects'):
            self.effects.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'effects'):
            self.effects.sync()
