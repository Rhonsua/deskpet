"""On-demand, illustrated desktop shop. The pet keeps running while it is open."""
from time import monotonic

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from deskpet.pet.catalog import AUTO_FULLNESS, AUTO_MEAL, CATEGORIES, ITEMS
from deskpet.pet.store import COMPANY_NOTES, COMPANY_STEP, COMPANY_STEPS, DAILY_INTERACTIONS
from .shop_art import SCENE_FPS, item_pixmap, scene_frame
from .theme import apply_light_palette


STYLE = """
QDialog#petShop, QWidget#shelves { background: #f5f3ec; color: #263d46; }
QWidget { font-family: "Microsoft YaHei UI"; font-size: 13px; color: #263d46; }
QLabel { background: transparent; border: none; }
QLabel#shopTitle { font-size: 26px; font-weight: 700; }
QLabel#wallet { background: #deeee8; color: #205748; border-radius: 12px; padding: 7px 14px; font-weight: 700; }
QLabel#stats, QLabel#detail { color: #536267; }
QFrame#product { background: #fffefa; border: 1px solid #d6d9cd; border-radius: 12px; }
QFrame#noteGuide { background: #edf4ee; border: 1px solid #c4d8ca; border-radius: 8px; }
QLabel#itemName { font-size: 17px; font-weight: 700; }
QLabel#price { color: #78501c; font-weight: 700; }
QLabel#effect { color: #2c645c; }
QPushButton { padding: 7px 12px; border: 1px solid #bfcac3; border-radius: 7px; background: #fffefa; }
QPushButton:hover { background: #e6eee7; border-color: #478378; }
QPushButton:focus { border: 2px solid #46796e; }
QPushButton:checked, QPushButton[buy="true"] { background: #286658; color: white; border-color: #286658; }
QPushButton[buy="true"]:hover { background: #1d5045; }
QPushButton:disabled { background: #eeeae2; color: #66665c; border-color: #d6d8cc; }
QScrollArea { background: transparent; border: none; }
QToolButton#sceneButton { background: #f2f5ed; color: #285a50; border: none; border-radius: 8px; }
QToolButton#sceneButton:hover { background: #dfece4; }
QCheckBox { spacing: 8px; background: transparent; }
QWidget#shopFilters { background: transparent; }
"""


class ScenePreview(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.Window)
        self.resize(320, 400)
        self.setMinimumSize(160, 180)
        self.key = ''
        self.explore_point = None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(round(1000 / SCENE_FPS))
        self.timer.timeout.connect(self.update)

    def present(self, item):
        if not self.key or ITEMS[self.key].panoramic != item.panoramic:
            self.resize(QSize(640, 360) if item.panoramic else QSize(320, 400))
        self.key = item.key
        self.explore_point = None
        self.setMouseTracking(item.panoramic)
        self.setWindowTitle(item.name + (' · 移动鼠标探索街景' if item.panoramic else ' · 动态预览'))
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if item.animated:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self.key and ITEMS[self.key].animated:
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def mouseMoveEvent(self, event):
        if self.key and ITEMS[self.key].panoramic:
            self.explore_point = event.position().toPoint()
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        if self.key:
            p = QPainter(self)
            if ITEMS[self.key].panoramic:
                from .panorama import panorama_frame
                p.fillRect(self.rect(), QColor('#e3eeec'))
                diameter = max(1, round(min(self.width(), self.height()) * .54))
                circle = QRect(0, 0, diameter, diameter)
                circle.moveCenter(self.explore_point if self.explore_point is not None else self.rect().center())
                frame = panorama_frame(item_pixmap(self.key), self.rect(), circle, self.devicePixelRatioF())
                p.drawPixmap(circle.topLeft(), frame)
            else:
                p.drawPixmap(0, 0, scene_frame(self.key, self.width(), self.height(), int(monotonic() * SCENE_FPS)))
            p.end()


class ProductCard(QFrame):
    def __init__(self, item, shop):
        super().__init__()
        self.item = item
        self.setObjectName('product')
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        has_preview = item.animated or item.panoramic
        self.setFixedHeight(338 if has_preview else 244)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)
        image = item_pixmap(item.key)
        if has_preview:
            picture = QToolButton()
            picture.setObjectName('sceneButton')
            picture.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            picture.setText('试逛圆窗' if item.panoramic else '预览动态效果')
            picture.setIcon(QIcon(image))
            picture.setIconSize(QSize(264, 148) if item.panoramic else QSize(132, 150))
            picture.setFixedHeight(176)
            picture.setAccessibleName(picture.text() + ' · ' + item.name)
            picture.clicked.connect(lambda: shop.preview_scene(item))
        else:
            picture = QLabel()
            picture.setAlignment(Qt.AlignCenter)
            picture.setPixmap(image.scaled(QSize(152, 78), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            picture.setFixedHeight(82)
        picture.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(picture)
        title = QLabel(item.name)
        title.setObjectName('itemName')
        layout.addWidget(title)
        detail = QLabel(item.description)
        detail.setObjectName('detail')
        detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        detail.setWordWrap(True)
        layout.addWidget(detail, 1)
        effects = {'food': f'饱食 +{item.fullness}  ·  心情 +{item.mood}',
                   'gift': f'心情 +{item.mood}', 'accessory': '发饰 · 可反复佩戴',
                   'background': '动态全景 · 永久' if item.animated else '静态布景 · 永久'}
        effect = QLabel('桌面全景 · 永久' if item.panoramic else effects[item.category])
        effect.setObjectName('effect')
        layout.addWidget(effect)
        foot = QHBoxLayout()
        price = QLabel(f'{item.price} 音符' if item.price else '免费')
        price.setObjectName('price')
        price.setAccessibleName(f'{item.price} 音符')
        foot.addWidget(price, 1)
        self.button = QPushButton()
        self.button.setProperty('buy', True)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(lambda: shop.select_item(item.key))
        foot.addWidget(self.button)
        layout.addLayout(foot)

    def refresh(self, pet, owned, settings):
        item = self.item
        usable = item.key in owned or pet['notes'] >= item.price
        hint = '' if usable else f'还差 {item.price - pet["notes"]} 音符'
        if item.category == 'food':
            label = '投喂'
            if pet['hunger'] >= 95:
                usable, hint = False, '已经吃饱啦'
        elif item.category == 'gift':
            label = '送礼'
            if pet['mood'] >= 100:
                usable, hint = False, '今天的心情已经满啦'
        elif settings[item.category] == item.key:
            label = '取下' if item.category == 'accessory' else '收起'
        else:
            label = '换上' if item.key in owned else '购买并换上'
        self.button.setText(label)
        self.button.setEnabled(usable)
        self.button.setAccessibleName(label + ' · ' + item.name)
        self.button.setToolTip(hint or f'{label}{item.name}')


class PetShop(QDialog):
    def __init__(self, panel):
        super().__init__(panel, Qt.Window)
        self.panel = panel
        self.setObjectName('petShop')
        self.setWindowTitle('天依的小铺')
        self.setWindowIcon(panel.windowIcon())
        self.resize(706, 690)
        self.setMinimumSize(364, 360)
        apply_light_palette(self)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel('天依的小铺')
        title.setObjectName('shopTitle')
        header.addWidget(title, 1)
        self.wallet = QLabel()
        self.wallet.setObjectName('wallet')
        header.addWidget(self.wallet)
        self.earn = QPushButton('赚音符')
        self.earn.setCheckable(True)
        self.earn.setAccessibleName('展开或收起今日音符获取进度')
        header.addWidget(self.earn)
        outer.addLayout(header)
        self.stats = QLabel()
        self.stats.setObjectName('stats')
        outer.addWidget(self.stats)
        self.note_guide = QFrame()
        self.note_guide.setObjectName('noteGuide')
        guide = QGridLayout(self.note_guide)
        guide.setContentsMargins(12, 6, 12, 6)
        guide.setVerticalSpacing(3)
        self.earning_status = {}
        labels = {k: '每日首次' + title for k, (title, _) in DAILY_INTERACTIONS.items()}
        labels['game'] += '（养成 MOD）'
        labels['company'] = f'陪伴每 {COMPANY_STEP // 60} 分钟 +{COMPANY_NOTES}'
        labels['listen'] = '听歌每 5 分钟（首小时 +6，之后 +2）'
        for row, (key, label) in enumerate(labels.items()):
            name = QLabel(label)
            name.setWordWrap(True)
            guide.addWidget(name, row, 0)
            self.earning_status[key] = QLabel()
            guide.addWidget(self.earning_status[key], row, 1, Qt.AlignRight | Qt.AlignVCenter)
        guide.setColumnStretch(0, 1)
        self.note_guide.hide()
        outer.addWidget(self.note_guide)
        self.earn.toggled.connect(self.toggle_note_guide)
        tabs = QHBoxLayout()
        tabs.setSpacing(5)
        self.categories = QButtonGroup(self)
        self.tab_buttons = {}
        icons = {'food': 'bao', 'gift': 'pinwheel', 'accessory': 'bow', 'background': 'garden'}
        for key, caption in CATEGORIES.items():
            button = QPushButton(caption)
            button.setCheckable(True)
            button.setIcon(QIcon(item_pixmap(icons[key])))
            button.setIconSize(QSize(20, 20))
            button.setCursor(Qt.PointingHandCursor)
            self.categories.addButton(button)
            self.tab_buttons[key] = button
            button.clicked.connect(lambda checked=False, value=key: self.show_category(value))
            tabs.addWidget(button)
        outer.addLayout(tabs)
        self.background_filter = QWidget()
        self.background_filter.setObjectName('shopFilters')
        filters = QHBoxLayout(self.background_filter)
        filters.setContentsMargins(0, 0, 0, 0)
        self.background_group = QButtonGroup(self)
        self.dynamic_button = QPushButton('动态全景')
        self.static_button = QPushButton('静态布景')
        self.panorama_button = QPushButton('桌面全景')
        for button in (self.static_button, self.dynamic_button, self.panorama_button):
            button.setCheckable(True)
            self.background_group.addButton(button)
            button.clicked.connect(lambda: self.show_category('background'))
            filters.addWidget(button)
        self.static_button.setChecked(True)
        filters.addStretch()
        outer.addWidget(self.background_filter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.shelves = QWidget()
        self.shelves.setObjectName('shelves')
        self.grid = QGridLayout(self.shelves)
        self.grid.setContentsMargins(0, 0, 4, 4)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.shelves)
        outer.addWidget(self.scroll, 1)
        self.auto = QCheckBox(f'饱食低于 {AUTO_FULLNESS}% 时自己买{AUTO_MEAL.name}（{AUTO_MEAL.price} 音符）')
        self.auto.toggled.connect(panel.store.set_auto_meal)
        outer.addWidget(self.auto)
        self.receipt = QLabel()
        self.receipt.setWordWrap(True)
        self.receipt.setObjectName('effect')
        self.receipt.hide()
        outer.addWidget(self.receipt)
        self.cards = {}
        self.preview = None
        self.category = ''
        self.columns = 0
        self.refresh_inventory()
        self.show_category('food')
        self.scroll.viewport().installEventFilter(self)

    def refresh_inventory(self):
        self.owned = self.panel.store.shop_owned()
        self.settings = self.panel.store.shop_settings()
        self.auto.blockSignals(True)
        self.auto.setChecked(bool(self.settings['auto_meal']))
        self.auto.blockSignals(False)
        self.last_stats = None

    def show_category(self, key):
        self.category = key
        self.tab_buttons[key].setChecked(True)
        self.background_filter.setVisible(key == 'background')
        for index in reversed(range(self.grid.count())):
            self.grid.takeAt(index).widget().hide()
        for item in ITEMS.values():
            if self.matches(item) and item.key not in self.cards:
                self.cards[item.key] = ProductCard(item, self)
        self.arrange()
        self.scroll.verticalScrollBar().setValue(0)
        self.last_stats = None
        self.refresh(self.panel.store.pet())

    def arrange(self):
        self.columns = self.column_count()
        for column in range(3):
            self.grid.setColumnStretch(column, int(column < self.columns))
        visible = [card for card in self.cards.values() if self.matches(card.item)]
        for index, card in enumerate(visible):
            if card.item.panoramic:
                self.grid.addWidget(card, index, 0, 1, self.columns)
            else:
                self.grid.addWidget(card, *divmod(index, self.columns))
            card.show()

    def matches(self, item):
        if item.category != self.category:
            return False
        if item.category != 'background':
            return True
        if item.panoramic:
            return self.panorama_button.isChecked()
        return (self.dynamic_button if item.animated else self.static_button).isChecked()

    def column_count(self):
        width = self.scroll.viewport().width()
        return 3 if width >= 615 else 2 if width >= 397 else 1

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.scroll.viewport() and self.columns != self.column_count():
            self.arrange()
        return super().eventFilter(obj, event)

    def preview_scene(self, item):
        if self.preview is None:
            self.preview = ScenePreview(self)
        self.preview.present(item)

    def hideEvent(self, event):
        if self.preview is not None:
            self.preview.hide()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_inventory()
        self.arrange()
        self.refresh(self.panel.store.pet())

    def toggle_note_guide(self, visible):
        self.note_guide.setVisible(visible)
        if visible:
            self.show_earnings(self.panel.store.stats())

    def show_earnings(self, stats):
        claimed = stats['daily_interactions']
        for source, (_, amount) in DAILY_INTERACTIONS.items():
            self.earning_status[source].setText(f'已得 {claimed[source]} 音符' if source in claimed else f'+{amount} 音符')
        minutes = int(stats['companion_seconds'] // 60)
        self.earning_status['company'].setText(f'{minutes}/{COMPANY_STEP * COMPANY_STEPS // 60} 分钟 · 已得 {claimed.get("company", 0)}')
        self.earning_status['listen'].setText(f'已得 {stats["reward_notes"]}/{stats["reward_limit"]} 音符')

    def refresh(self, pet, stats=None):
        if self.earn.isChecked():
            self.show_earnings(stats if stats is not None else self.panel.store.stats())
        values = (pet['notes'], pet['hunger'], pet['mood'])
        if values == self.last_stats:
            return
        self.last_stats = values
        self.wallet.setText(f'{pet["notes"]} 音符')
        self.stats.setText(f'饱食 {pet["hunger"]}%     心情 {pet["mood"]}%')
        for card in self.cards.values():
            if self.matches(card.item):
                card.refresh(pet, self.owned, self.settings)

    def select_item(self, key):
        item = ITEMS[key]
        remove = self.settings.get(item.category) == key
        _, message = self.panel.buy_shop_item(key, remove=remove)
        self.refresh_inventory()
        self.refresh(self.panel.store.pet())
        self.receipt.setText(message)
        self.receipt.show()
