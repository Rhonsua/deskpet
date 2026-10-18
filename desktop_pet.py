"""Character-first desktop interactions, local dialogue, state animation and a small toolbar."""
import math
import random
import time

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion, QTransform, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
    QProgressBar, QSlider, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget, QCheckBox,
)

from pet_store import FOODS
from visual_style import sprite_bounds, update_cover
from ui_theme import CONTROL_STYLE
from edge_docking import EDGES, clamp_position, dock_position, nearest_edge, edge_gap, pushed_edge
from pet_behavior import MODES, PetBehavior
from singing_motion import SingingRig, singing_pose
from character_packs import builtin_sources


POPUP_STYLE = """
QFrame#PetPopup { background: #FCFEFF; border: 1px solid #AFC8D3; border-radius: 6px; }
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #3C5564; }
QLabel { background: transparent; border: none; }
QLabel#Muted { color: #869CA7; font-size: 11px; }
QPushButton { background: #FFFFFF; border: 1px solid #D9E5EA; padding: 6px 9px; border-radius: 4px; }
QPushButton:hover { background: #E1F0F5; border-color: #89B8C9; }
QPushButton:checked { background: #D9EDF3; color: #36788E; }
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
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet(POPUP_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.label = QLabel()
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
        self.setStyleSheet(POPUP_STYLE)
        self.setFixedWidth(336)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(9)
        title = QHBoxLayout()
        self.name = QLabel('洛天依')
        self.name.setStyleSheet('font-weight: 600; color: #3C7A92;')
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
        self.name.setText(f"洛天依  Lv.{data['level']}     音符 {data['notes']}")
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
            self.content.addWidget(QLabel(title[:24]))
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
        else:
            hint = QLabel('点头部摸摸 · 拖动提起 · 双击/右键菜单')
            hint.setObjectName('Muted')
            self.content.addWidget(hint)
            self.add_button('和天依说：一起加油吧', lambda: self.pet.reply())
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
        self.panel = panel_factory(self)
        self.behavior.set_mode(self.panel.settings.value('activity_mode', 'idle')
                               if self.panel.settings.value('activity_mode', 'idle') in MODES else 'idle')
        self.variant = self.panel.settings.value('visual_variant', 'refined')
        if self.panel.settings.value('appearance_revision', '') != 'refined-smooth-v1':
            self.variant = 'refined'
            self.panel.settings.setValue('appearance_revision', 'refined-smooth-v1')
        self.scale = float(self.panel.settings.value('pet_scale', 1.0))
        self.bubble = Bubble(self)
        self.toolbar = PetToolbar(self)
        self.set_scale(self.scale)
        self.set_variant(self.variant)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.touch)
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.begin_drag)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)
        self.tray = QSystemTrayIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume), self)
        menu = QMenu()
        menu.setStyleSheet(CONTROL_STYLE)
        menu.addAction('显示天依', self.restore)
        menu.addAction('互动菜单', self.toolbar.toggle)
        menu.addAction('歌单', lambda: self.open_tools(0))
        menu.addAction('设置', lambda: self.open_tools(2))
        self.passthrough_action = menu.addAction('鼠标穿透')
        self.passthrough_action.setCheckable(True)
        self.passthrough_action.toggled.connect(self.set_mouse_passthrough)
        menu.addAction('关闭鼠标穿透并找回天依', self.recover_input)
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
        self.tray.setToolTip('洛天依 · 鼠标穿透中，右键托盘可关闭' if enabled else '洛天依 · 右键打开菜单')

    def recover_input(self):
        self.set_mouse_passthrough(False)
        self.restore()
        self.reveal_dock()
        self.bubble.say('鼠标穿透已关闭，可以继续拖动和互动。')

    def set_variant(self, variant):
        self.variant = variant
        self.frames = {}
        sources = builtin_sources(variant)
        filename = sources['idle']
        for state, path in sources.items():
            cache_key = str(path)
            if cache_key in self.pixmap_cache:
                self.frames[state] = self.pixmap_cache[cache_key]
                continue
            pixmap = QPixmap(cache_key)
            if not pixmap.isNull():
                self.frames[state] = pixmap.copy(sprite_bounds(pixmap))
                self.pixmap_cache[cache_key] = self.frames[state]
        self.sprite = self.frames.get('idle', QPixmap())
        self.prepare_frames()
        update_cover(self.panel, filename, self.sprite)
        self.panel.settings.setValue('visual_variant', variant)
        self.panel.appearance.blockSignals(True)
        self.panel.appearance.setCurrentIndex(self.panel.appearance.findData(variant))
        self.panel.appearance.blockSignals(False)
        self.update()

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

    def prepare_frames(self):
        self.scaled_frames = {
            name: pixmap.scaled(round(236 * self.scale), round((154 if name in ('sleep', 'phone') else 270) * self.scale),
                                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            for name, pixmap in self.frames.items()
        }
        self.frame_masks = {name: QRegion(pixmap.mask()) for name, pixmap in self.scaled_frames.items()}
        self.singing_rigs = {name: SingingRig(pixmap, self.frame_masks[name])
                             for name, pixmap in self.scaled_frames.items() if name.startswith('sing-')}

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

    def dock_transform(self):
        transform = QTransform()
        if not self.dock_edge:
            return transform
        amount = 1.0 - self.dock_reveal
        head = QPointF(self.width() / 2, 93 * self.scale)
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
            desired = self.press_point - QPoint(self.width() // 2, round(93 * self.scale))
            self.move(clamp_position(desired, self.size(), self.screen_bounds()))
            self.drag_offset = self.press_point - self.pos()
        self.behavior.begin_drag()
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
        self.behavior.tick(delta)
        self.update()

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
        state = 'idle'
        angle, y, sx, sy = 0.0, 0.0, 1.0, 1.0
        if activity == 'lift':
            state, angle, y = 'lift', math.sin(elapsed * 5) * 5, -5
        elif activity == 'eat':
            state, y = 'eat', math.sin(elapsed * 13) * 1.5
            sx = 1 + math.sin(elapsed * 13) * 0.008
        elif activity in ('happy', 'poke'):
            state = 'happy' if activity == 'happy' else 'lift'
            angle = math.sin(elapsed * 11) * (2 if activity == 'happy' else 4)
            y = -abs(math.sin(elapsed * 7)) * 7
        elif activity == 'land':
            sy = 1 - max(0, 1 - elapsed / 0.6) * math.sin(elapsed * 14) * 0.10
            sx = 2 - sy
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
        transform.translate(-image.width() / 2, -image.height())
        resting = key in ('sleep', 'phone')
        if not resting:
            transform *= self.dock_transform()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setTransform(transform)
        local_mask = self.frame_masks[key]
        if key in self.singing_rigs:
            local_mask = self.singing_rigs[key].draw(painter, motion_time, scale)
        else:
            painter.drawPixmap(0, 0, image)
        if key == 'phone':
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
        if (not self.dock_edge or self.dock_reveal > 0.95) and activity in ('happy', 'sing', 'turn', 'sleep'):
            color = QColor('#C87991') if activity == 'happy' else QColor('#69A3BA')
            for i in range(3):
                phase = (now * 0.8 + i / 3) % 1
                x = (35 + i * 76 + math.sin(now + i) * 6) * scale
                y = ((190 if resting else 120) - phase * 60) * scale
                painter.setOpacity((1 - phase) * 0.9)
                painter.save()
                painter.translate(x, y)
                painter.scale(scale * 0.65, scale * 0.65)
                path = QPainterPath()
                if activity == 'happy':
                    path.moveTo(0, -4)
                    path.cubicTo(-11, -15, -17, 0, 0, 11)
                    path.cubicTo(17, 0, 11, -15, 0, -4)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(color)
                    painter.drawPath(path)
                elif activity == 'sleep':
                    path.moveTo(0, -9)
                    path.lineTo(10, -9)
                    path.lineTo(0, 0)
                    path.lineTo(10, 0)
                    painter.setPen(QPen(color, 2))
                    painter.drawPath(path)
                else:
                    painter.setPen(QPen(color, 2))
                    painter.drawLine(4, 3, 4, -12)
                    painter.drawLine(4, -12, 11, -8)
                    painter.setBrush(color)
                    painter.drawEllipse(-3, 0, 7, 5)
                painter.restore()
                mask = mask.united(QRegion(round(x) - 16, round(y) - 18, 32, 34))
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
                               event.position().y() < self.height() * 0.57)
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
        super().hideEvent(event)
