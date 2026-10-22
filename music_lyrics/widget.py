"""Explicit lyric imports and exact-source binding; all previews are plain text."""
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QCheckBox, QSpinBox, QComboBox, QFormLayout, QFileDialog,
                               QPlainTextEdit, QMessageBox, QColorDialog)
from ui_theme import apply_light_palette, CONTROL_STYLE


class LyricsWidget(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._shown_binding = None
        apply_light_palette(self)
        self.setStyleSheet('QWidget { background:white; color:black; } '
                          'QPushButton { padding:6px 10px; }' + CONTROL_STYLE)
        layout = QVBoxLayout(self)
        notice = QLabel('字幕只跟随本地/B站的真实播放位置；暂停会停在原句。\n'
                        '云端歌曲与翻唱、Live、MV 版本可能不同，绑定前请确认；不猜测歌名匹配。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.source_label = QLabel()
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        row = QHBoxLayout()
        self.import_button = QPushButton('为当前音源导入 LRC / SRT')
        self.import_button.clicked.connect(self.import_file)
        row.addWidget(self.import_button)
        self.unbind_button = QPushButton('解除当前绑定')
        self.unbind_button.clicked.connect(self.unbind)
        row.addWidget(self.unbind_button)
        layout.addLayout(row)
        layout.addWidget(QLabel('待绑定缓存（选择后点击绑定；当前绑定会在切歌时自动选中）'))
        self.cache_combo = QComboBox()
        layout.addWidget(self.cache_combo)
        row = QHBoxLayout()
        self.bind_button = QPushButton('将选中缓存绑定到当前音源…')
        self.bind_button.clicked.connect(self.bind_cache)
        row.addWidget(self.bind_button)
        self.refresh_button = QPushButton('刷新缓存列表')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        form = QFormLayout()
        self.offset_input = QSpinBox()
        self.offset_input.setRange(-600000, 600000)
        self.offset_input.setSingleStep(100)
        self.offset_input.setSuffix(' ms')
        form.addRow('歌词提前(+) / 延后(-)', self.offset_input)
        self.offset_button = QPushButton('保存当前绑定偏移')
        self.offset_button.clicked.connect(self.save_offset)
        form.addRow(self.offset_button)
        self.enabled = QCheckBox('显示角色附近的歌词字幕')
        self.enabled.setChecked(controller.settings['enabled'])
        form.addRow(self.enabled)
        self.passthrough = QCheckBox('左键穿透（右键歌词仍可打开设置）')
        self.passthrough.setChecked(controller.settings['left_passthrough'])
        form.addRow(self.passthrough)
        self.color_button = QPushButton('选择歌词颜色…')
        self.color_button.clicked.connect(self.choose_color)
        form.addRow('歌词颜色', self.color_button)
        self.font_input = QSpinBox()
        self.font_input.setRange(10, 48)
        self.font_input.setValue(controller.settings['font_size'])
        form.addRow('字号', self.font_input)
        self.position_input = QComboBox()
        self.position_input.addItem('角色下方', 'below')
        self.position_input.addItem('角色上方', 'above')
        self.position_input.setCurrentIndex(1 if controller.settings['position'] == 'above' else 0)
        form.addRow('位置', self.position_input)
        self.x_input, self.y_input = QSpinBox(), QSpinBox()
        for spin, key in ((self.x_input, 'x_offset'), (self.y_input, 'y_offset')):
            spin.setRange(-2000, 2000)
            spin.setSuffix(' px')
            spin.setValue(controller.settings[key])
        form.addRow('水平微调（右为正）', self.x_input)
        form.addRow('与角色间距', self.y_input)
        layout.addLayout(form)
        self.settings_button = QPushButton('保存字幕显示设置')
        self.settings_button.clicked.connect(self.save_settings)
        layout.addWidget(self.settings_button)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText('绑定歌词的纯文本预览；无时间轴的纯文本不会假装同步。')
        self.preview.setMaximumHeight(120)
        layout.addWidget(self.preview, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.enabled.toggled.connect(self.toggle_enabled)
        self.passthrough.toggled.connect(self.toggle_passthrough)
        controller.changed.connect(self.refresh)
        controller.bound.connect(self.binding_changed)
        self.refresh()

    def binding_changed(self, song_id, source_key):
        if source_key == self.controller.source_key:
            self._shown_binding = None
            self.refresh()

    def error(self, error):
        self.status.setText('歌词操作未保存，请重试：' + str(error))

    def refresh(self):
        controller = self.controller
        for control, key in ((self.enabled, 'enabled'), (self.passthrough, 'left_passthrough')):
            control.blockSignals(True)
            control.setChecked(controller.settings[key])
            control.blockSignals(False)
        self.color_button.setText('选择歌词颜色… ' + controller.settings['color'])
        source = controller.source_key
        if source.startswith('local:'):
            description = '本地文件：' + source[6:]
        elif source.startswith('bilibili:'):
            parts = source.split(':')
            description = 'B站：' + parts[1] + ' 第 ' + parts[2] + ' P' if len(parts) == 3 else 'B站音源'
        else:
            description = '未播放'
        self.source_label.setText('当前音源 · ' + description[:110] + ('…' if len(description) > 110 else ''))
        self.source_label.setToolTip(description)
        try:
            selected = self.cache_combo.currentData()
            binding = (source, controller.binding['id'] if controller.binding else None)
            if binding != self._shown_binding and controller.binding:
                selected = controller.binding['id']
            self.cache_combo.clear()
            for item in controller.get_cached():
                origin = '网易云 ' + item['song_id'] if item['source'] == 'netease' else '文件'
                self.cache_combo.addItem(item['title'][:70] + ' · ' + origin, item['id'])
                self.cache_combo.setItemData(self.cache_combo.count() - 1,
                                            item['title'] + '\n来源：' + origin + '\n缓存时间：' + item['fetched_at'],
                                            Qt.ItemDataRole.ToolTipRole)
            index = self.cache_combo.findData(selected)
            if index >= 0:
                self.cache_combo.setCurrentIndex(index)
            self._shown_binding = binding
            self.offset_input.setValue(controller.binding['offset_ms'] if controller.binding else 0)
            self.preview.setPlainText(controller.document.plain_text if controller.document else '')
            self.status.setText(controller.status)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)
        self.import_button.setEnabled(bool(source))
        self.bind_button.setEnabled(bool(source) and self.cache_combo.count() > 0)
        self.offset_button.setEnabled(controller.binding is not None)
        self.unbind_button.setEnabled(controller.binding is not None)

    def import_file(self):
        source = self.controller.source_key
        if not source:
            return
        path, _ = QFileDialog.getOpenFileName(self, '导入当前音源的歌词', '', '歌词文件 (*.lrc *.srt)')
        if path:
            try:
                self._shown_binding = None
                self.controller.import_file(path, source)
            except (ValueError, OSError, sqlite3.Error) as error:
                self.error(error)

    def bind_cache(self):
        source = self.controller.source_key
        lyric_id = self.cache_combo.currentData()
        if not source or lyric_id is None:
            return
        question = ('将「' + self.cache_combo.currentText() + '」绑定到下面这个准确音源？\n\n'
                    + source + '\n\n请确认演唱版本和片头一致，不会自动修正剪辑差异。')
        if QMessageBox.question(self, '确认歌词与音源绑定', question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.bind_cached(lyric_id, source)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def save_offset(self):
        try:
            self.controller.set_offset(self.offset_input.value())
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def save_settings(self):
        try:
            self.controller.configure(enabled=self.enabled.isChecked(), font_size=self.font_input.value(),
                                      position=self.position_input.currentData(), x_offset=self.x_input.value(),
                                      y_offset=self.y_input.value())
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def toggle_enabled(self, enabled):
        try:
            self.controller.configure(enabled=enabled)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)

    def toggle_passthrough(self, enabled):
        try:
            self.controller.configure(left_passthrough=enabled)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.refresh()
            self.error(error)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.controller.settings['color']), self, '选择歌词颜色')
        if color.isValid():
            try:
                self.controller.configure(color=color.name())
            except (ValueError, OSError, sqlite3.Error) as error:
                self.error(error)

    def unbind(self):
        try:
            self.controller.unbind()
        except (ValueError, OSError, sqlite3.Error) as error:
            self.error(error)
