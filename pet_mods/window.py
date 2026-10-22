"""On-demand optional mod controls and one shared reminder policy."""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QCheckBox, QTabWidget, QFormLayout, QSpinBox, QPushButton,
                               QMessageBox, QScrollArea, QFrame)

from ui_theme import apply_light_palette, style_combo, CONTROL_STYLE


STYLE = '''
QWidget { background: #FFFFFF; color: #000000; font-family: 'Microsoft YaHei UI'; font-size: 12px; }
QLabel { background: transparent; }
QLineEdit, QPlainTextEdit, QListWidget, QDateTimeEdit, QSpinBox {
    border: 1px solid #AFC8D3; border-radius: 4px; padding: 5px;
    color: #000000; background: #FFFFFF; selection-background-color: #DCECF2; selection-color: #000000;
}
QPushButton { border: 1px solid #91AAB7; border-radius: 4px; padding: 6px 10px; background: #FFFFFF; }
QPushButton:hover { background: #EDF6F9; }
QPushButton:disabled { color: #777777; border-color: #D9E4EA; }
QTabBar::tab { padding: 8px 15px; }
QTabBar::tab:selected { border-bottom: 2px solid #4D8C9F; }
''' + CONTROL_STYLE


def label(value):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class ModsWindow(QWidget):
    def __init__(self, pet, manager):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.pet, self.manager = pet, manager
        self._page_key = None
        self._choice_index = 0
        self.setWindowTitle('桌宠 · 扩展功能')
        self.resize(700, 780)
        self.setMinimumSize(580, 560)
        apply_light_palette(self)
        self.setStyleSheet(STYLE)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        content = QWidget()
        layout = QVBoxLayout(content)
        row = QHBoxLayout()
        self.choice = QComboBox()
        style_combo(self.choice)
        for manifest in manager.manifests():
            self.choice.addItem(manifest.name, manifest.id)
        row.addWidget(self.choice, 1)
        self.enabled = QCheckBox('启用此功能')
        row.addWidget(self.enabled)
        layout.addLayout(row)
        folder = QPushButton('打开 Mod 文件夹')
        folder.clicked.connect(self.open_folder)
        layout.addWidget(folder)
        self.description = label('')
        layout.addWidget(self.description)
        self.page_container = QWidget()
        self.page_layout = QVBoxLayout(self.page_container)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_scroll.setWidget(self.page_container)
        layout.addWidget(page_scroll, 1)
        self.tabs.addTab(content, '扩展功能')
        policy_page = QWidget()
        policy_layout = QVBoxLayout(policy_page)
        policy_layout.addWidget(label('以下设置统一用于所有扩展提醒。桌宠退出时不运行提醒，重新打开后检查；'
                                      '睡觉、玩手机、拖动或正在使用菜单时暂不打扰。'))
        self.quiet = QCheckBox('每天固定时段免打扰')
        policy_layout.addWidget(self.quiet)
        self.sound = QCheckBox('显示提醒时播放提示音（跟随系统声音设置）')
        policy_layout.addWidget(self.sound)
        form = QFormLayout()
        self.quiet_start, self.quiet_end = QSpinBox(), QSpinBox()
        for widget in (self.quiet_start, self.quiet_end):
            widget.setRange(0, 23)
            widget.setSuffix(' 点')
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 20)
        self.daily_limit.setSuffix(' 次')
        self.interval = QSpinBox()
        self.interval.setRange(1, 1440)
        self.interval.setSuffix(' 分钟')
        form.addRow('免打扰开始', self.quiet_start)
        form.addRow('免打扰结束', self.quiet_end)
        form.addRow('每天最多提醒', self.daily_limit)
        form.addRow('两次提醒至少间隔', self.interval)
        policy_layout.addLayout(form)
        policy_layout.addWidget(label('时间使用电脑本地时区；开始和结束相同表示全天免打扰。'
                                      '未显示的提醒不占次数；各 Mod 可能另有提醒间隔。'))
        self.policy_save = QPushButton('保存提醒设置')
        self.policy_save.clicked.connect(self.save_policy)
        policy_layout.addWidget(self.policy_save)
        policy_layout.addStretch()
        self.tabs.addTab(policy_page, '提醒设置')
        host = getattr(pet, 'mod_host', None)
        self.status = label(manager.warning or getattr(host, 'discovery_warning', '') or
                            'Mod 可以访问本机文件，请仅安装可信来源。解压到 Mod 文件夹后重启桌宠。')
        outer.addWidget(self.status)
        self.choice.currentIndexChanged.connect(self.change_choice)
        self.enabled.toggled.connect(self.toggle_enabled)
        self.load_policy()
        self.sync_state(force=True)

    def open_folder(self):
        path = self.pet.mod_host.packages_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.status.setText('无法创建 Mod 文件夹，请检查目录权限：' + str(path))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.status.setText('请手动打开：' + str(path))

    def confirm_discard(self):
        page = self.page_layout.itemAt(0).widget() if self.page_layout.count() else None
        has_changes = getattr(page, 'has_unsaved_changes', None)
        try:
            changed = bool(has_changes and has_changes())
        except Exception:
            # An optional plugin hook must not break navigation or silently
            # authorize discarding contents when it cannot inspect the page.
            changed = True
        if not changed:
            return True
        return QMessageBox.question(self, '未保存的编辑',
            '还有未保存的编辑。继续会丢弃这些编辑，已保存的数据会保留。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def change_choice(self, index):
        if not self.confirm_discard():
            self.choice.blockSignals(True)
            self.choice.setCurrentIndex(self._choice_index)
            self.choice.blockSignals(False)
            return
        self._choice_index = index
        self.sync_state(force=True)

    def load_policy(self):
        policy = self.manager.get_policy()
        self.quiet.setChecked(policy['quiet_enabled'])
        self.sound.setChecked(policy.get('sound_enabled', True))
        self.quiet_start.setValue(policy['quiet_start'])
        self.quiet_end.setValue(policy['quiet_end'])
        self.daily_limit.setValue(policy['daily_limit'])
        self.interval.setValue(policy['min_interval_minutes'])

    def save_policy(self):
        try:
            success = self.manager.set_policy(quiet_enabled=self.quiet.isChecked(),
                sound_enabled=self.sound.isChecked(),
                quiet_start=self.quiet_start.value(), quiet_end=self.quiet_end.value(),
                daily_limit=self.daily_limit.value(), min_interval_minutes=self.interval.value())
            self.status.setText('提醒设置已保存。' if success else self.manager.warning or '保存失败，请重试。')
        except (OSError, ValueError) as error:
            self.status.setText('提醒设置未保存：' + str(error))

    def toggle_enabled(self, enabled):
        key = self.choice.currentData()
        if not key:
            return
        if not enabled and not self.confirm_discard():
            self.enabled.blockSignals(True)
            self.enabled.setChecked(True)
            self.enabled.blockSignals(False)
            return
        self.page_container.setEnabled(False)
        success = self.manager.set_enabled(key, enabled)
        self.sync_state(force=True)
        self.status.setText(('已启用。' if enabled else '已停用，存档保留。') if success else
                            self.manager.error(key) or self.manager.warning or '切换失败，请重试。')

    def sync_state(self, force=False):
        key = self.choice.currentData()
        enabled = bool(key and self.manager.is_enabled(key))
        state = (key, enabled, self.manager.error(key) if key else '')
        if not force and state == self._page_key:
            return
        self._page_key = state
        self.enabled.blockSignals(True)
        self.enabled.setChecked(enabled)
        self.enabled.setEnabled(bool(key))
        self.enabled.blockSignals(False)
        self.page_container.setEnabled(enabled)
        manifest = next((item for item in self.manager.manifests() if item.id == key), None)
        self.description.setText(manifest.description if manifest else '')
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if enabled:
            widget = self.manager.create_widget(key, self.page_container)
            if isinstance(widget, QWidget):
                self.page_layout.addWidget(widget)
                return
            if widget is None and self.manager.is_enabled(key):
                self.page_layout.addWidget(label('此 Mod 已启用，没有独立设置页面。'))
                self.page_layout.addStretch()
                return
            if widget is not None:
                self.manager.set_enabled(key, False)
                self.status.setText('此 Mod 的设置页面无效，已停用。')
            self.enabled.blockSignals(True)
            self.enabled.setChecked(False)
            self.enabled.blockSignals(False)
        self.page_layout.addWidget(label('勾选启用后可使用此 Mod。停用会保留已保存的数据。' if key else
            '尚未安装 Mod。点击“打开 Mod 文件夹”，将 Mod 压缩包中的文件夹解压到这里，'
            '重启桌宠后选择并启用。主程序不附带目标陪伴等 Mod。'))
        self.page_layout.addStretch()
        if key and self.manager.error(key):
            self.status.setText('此功能已停用：' + self.manager.error(key))

    def show_mods(self):
        from desktop_pet import clamp_near
        self.sync_state()
        self.pet.toolbar.hide()
        self.pet.reveal_dock()
        clamp_near(self.pet, self)
        self.show()
        self.raise_()
        self.activateWindow()
