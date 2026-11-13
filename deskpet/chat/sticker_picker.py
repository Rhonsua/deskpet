"""Anchored sticker tray: click to compose, hover to preview, right-click for extras."""
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QEvent, QPoint
from PySide6.QtGui import QIcon, QPixmap, QMovie
from PySide6.QtWidgets import (QDialog, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QToolButton, QTabBar, QLineEdit, QListWidget, QListWidgetItem, QFileDialog,
    QAbstractItemView, QMenu)
from .sticker_service import StickerService


class StickerPicker(QDialog):
    selected = Signal(str)
    sent = Signal(str)
    GROUPS = ('最近', '收藏', '天依', '阿绫', '我的')

    def __init__(self, catalog, config, parent=None):
        super().__init__(parent, Qt.Popup)
        self.catalog = catalog
        self.movie = None
        self.anchor = None
        self.hovered = None
        from deskpet.ui.theme import apply_light_palette
        apply_light_palette(self)
        self.setObjectName('StickerPicker')
        self.setAutoFillBackground(True)
        self.setWindowTitle('表情')
        self.setFixedSize(420, 404)
        self.setStyleSheet('''
            QDialog#StickerPicker, QFrame#StickerPreview { background: #F5FAFD; color: #193746; border: 1px solid #AAC7D5; border-radius: 8px; }
            QLabel { color: #466576; background: transparent; font-size: 12px; }
            QListWidget { background: #FFFFFF; color: #193746; border: none; border-radius: 6px; }
            QListWidget::item { border-radius: 6px; }
            QListWidget::item:hover, QListWidget::item:selected { background: #DCEFF8; color: #193746; }
            QLineEdit { background: #FFFFFF; color: #193746; border: 1px solid #BDD3DE; padding: 6px; border-radius: 5px; }
            QToolButton { background: #FFFFFF; color: #193746; border: 1px solid #BDD3DE; border-radius: 5px; padding: 5px 9px; }
            QTabBar::tab { background: transparent; color: #466576; padding: 7px 12px; border: none; }
            QTabBar::tab:selected { background: #DCEFF8; color: #164D69; border-radius: 5px; }
            QMenu { background: #FFFFFF; color: #193746; border: 1px solid #BDD3DE; padding: 4px; }
            QMenu::item { padding: 7px 16px; }
            QMenu::item:selected { background: #DCEFF8; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('搜索表情，如：开心、抱抱')
        self.query.setMaxLength(40)
        self.query.setClearButtonEnabled(True)
        row.addWidget(self.query, 1)
        more = QToolButton()
        more.setText('+')
        more.setToolTip('导入图片、GIF 或联网搜索')
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction('导入图片 / GIF…', self.import_images)
        menu.addAction('联网找表情', self.search)
        menu.addAction('取消搜索', self.cancel_search)
        more.setMenu(menu)
        row.addWidget(more)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setIconSize(QSize(64, 64))
        self.list.setGridSize(QSize(76, 89))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.viewport().installEventFilter(self)
        self.list.itemClicked.connect(lambda item: self.choose(item.data(Qt.UserRole)))
        self.list.itemEntered.connect(self.hover)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.list, 1)
        self.details = QLabel('点图加入消息，再点发送 · 右键收藏或单独发 · 悬停预览')
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setMaximumHeight(38)
        layout.addWidget(self.details)
        self.tabs = QTabBar()
        self.tabs.setExpanding(True)
        for name in self.GROUPS:
            self.tabs.addTab(name)
        self.tabs.setCurrentIndex(0 if catalog.panel_state()['recent'] else 2)
        layout.addWidget(self.tabs)
        self.preview_frame = QFrame(self, Qt.ToolTip)
        self.preview_frame.setObjectName('StickerPreview')
        preview_layout = QVBoxLayout(self.preview_frame)
        self.image = QLabel()
        self.image.setFixedSize(160, 160)
        self.image.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.image)
        self.preview_title = QLabel()
        self.preview_title.setAlignment(Qt.AlignCenter)
        self.preview_title.setTextFormat(Qt.PlainText)
        self.preview_title.setMaximumWidth(160)
        self.preview_title.setWordWrap(True)
        preview_layout.addWidget(self.preview_title)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.preview)
        self.service = StickerService(catalog, config, self)
        self.service.status.connect(self.details.setText)
        self.service.failed.connect(self.details.setText)
        self.service.ready.connect(self.imported)
        self.query.textChanged.connect(self.refresh)
        self.tabs.currentChanged.connect(self.refresh)
        self.refresh()

    def open_at(self, anchor):
        self.anchor = anchor
        origin = anchor.mapToGlobal(QPoint(0, 0))
        screen = anchor.screen().availableGeometry()
        x = max(screen.left(), min(origin.x(), screen.right() - self.width() + 1))
        y = origin.y() - self.height() - 6
        if y < screen.top():
            y = min(origin.y() + anchor.height() + 6, screen.bottom() - self.height() + 1)
        self.move(x, max(screen.top(), y))
        self.show()
        self.query.setFocus()

    def refresh(self):
        self.clear_preview()
        self.list.clear()
        group = self.tabs.currentIndex()
        state = self.catalog.panel_state()
        if group < 2:
            entries = [self.catalog.get(k) for k in state['recent' if group == 0 else 'favorites']]
        else:
            entries = self.catalog.items.values()
        query = self.query.text().strip().casefold()
        for item in entries:
            if group == 4 and item.id not in self.catalog.custom:
                continue
            if group in (2, 3) and item.character != ('洛天依' if group == 2 else '乐正绫'):
                continue
            if query and query not in (item.title + item.character).casefold():
                continue
            pixmap = QPixmap(str(item.path)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            widget = QListWidgetItem(QIcon(pixmap), item.title + (' GIF' if item.animated else ''))
            widget.setData(Qt.UserRole, item.id)
            self.list.addItem(widget)

    def current(self):
        item = self.list.currentItem()
        return self.catalog.get(item.data(Qt.UserRole)) if item else None

    def hover(self, item):
        self.clear_preview()
        self.hovered = item.data(Qt.UserRole)
        self.preview_timer.start(220)

    def clear_preview(self):
        self.preview_timer.stop()
        self.hovered = None
        self.preview_frame.hide()
        self.image.clear()
        if self.movie:
            self.movie.stop()
            self.movie.setFileName('')
            self.movie.deleteLater()
            self.movie = None

    def preview(self):
        item = self.catalog.get(self.hovered)
        if not item or not self.isVisible():
            return
        pixmap = QPixmap(str(item.path))
        size = pixmap.size().scaled(160, 160, Qt.KeepAspectRatio)
        if item.animated:
            self.movie = QMovie(str(item.path), parent=self)
            self.movie.setScaledSize(size)
            self.image.setMovie(self.movie)
            self.movie.start()
        else:
            self.image.setPixmap(pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview_title.setText(item.title + (' · GIF' if item.animated else ''))
        self.preview_frame.adjustSize()
        screen = self.screen().availableGeometry()
        x = self.x() + self.width() + 4
        if x + self.preview_frame.width() > screen.right():
            x = self.x() - self.preview_frame.width() - 4
        self.preview_frame.move(max(screen.left(), x), max(screen.top(), min(self.y(), screen.bottom() - self.preview_frame.height())))
        self.preview_frame.show()

    def eventFilter(self, watched, event):
        if watched == self.list.viewport() and event.type() in (QEvent.Leave, QEvent.Wheel, QEvent.MouseButtonPress):
            self.clear_preview()
        return super().eventFilter(watched, event)

    def context_menu(self, point):
        widget = self.list.itemAt(point)
        if not widget:
            return
        self.clear_preview()
        self.list.setCurrentItem(widget)
        item = self.current()
        menu = QMenu(self)
        favorite = item.id in self.catalog.panel_state()['favorites']
        collect = menu.addAction('取消收藏' if favorite else '收藏')
        send = menu.addAction('立即单独发送')
        identify = menu.addAction('识别图中角色') if item.id in self.catalog.custom else None
        choice = menu.exec(self.list.viewport().mapToGlobal(point))
        if choice is collect:
            try:
                self.catalog.remember(item.id, favorite=True)
                self.refresh()
            except OSError:
                self.details.setText('收藏保存失败，请检查磁盘空间。')
        elif choice is send:
            self.sent.emit(item.id)
            self.accept()
        elif identify is not None and choice is identify:
            self.service.identify(item.id)

    def import_images(self):
        self.hide()
        paths, _ = QFileDialog.getOpenFileNames(self.parentWidget(), '导入表情包', '', '图片 (*.png *.jpg *.jpeg *.webp *.gif)')
        if self.anchor:
            self.open_at(self.anchor)
        errors = []
        last = None
        for path in paths[:20]:
            try:
                last = self.catalog.import_file(path)
            except (ValueError, OSError) as error:
                errors.append(str(error))
        if last:
            self.imported(last.id)
        if errors:
            self.details.setText(errors[0])

    def imported(self, key):
        self.query.clear()
        self.tabs.setCurrentIndex(4)
        self.refresh()
        for index in range(self.list.count()):
            if self.list.item(index).data(Qt.UserRole) == key:
                self.list.setCurrentRow(index)
                self.list.scrollToItem(self.list.item(index))
                break
        self.details.setText('已加入图库，点表情放入消息，再点发送。')

    def search(self):
        group = self.tabs.currentIndex()
        if group not in (2, 3):
            self.details.setText('先切到天依或阿绫，输入关键词后再联网找表情。')
            return
        self.details.setText('联网搜索并通过看图 API 确认人物…')
        self.service.search('洛天依' if group == 2 else '乐正绫', self.query.text())

    def cancel_search(self):
        self.service.cancel()
        self.details.setText('已取消搜索。')

    def choose(self, key=None):
        item = self.catalog.get(key) if key else self.current()
        if item:
            self.selected.emit(item.id)
            self.accept()

    def hideEvent(self, event):
        self.clear_preview()
        self.service.cancel()
        super().hideEvent(event)

    def done(self, result):
        self.service.shutdown()
        self.clear_preview()
        super().done(result)
