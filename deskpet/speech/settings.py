"""Settings and audition for the local Tianyi voice."""
from pathlib import Path
from PySide6.QtCore import QFileSystemWatcher, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLineEdit, QHBoxLayout,
                               QPushButton, QFileDialog, QDialogButtonBox, QLabel, QWidget,
                               QToolButton, QSlider, QMessageBox, QComboBox)

from deskpet.ui.icon import application_icon
from deskpet.ui.theme import apply_light_palette
from .config import installation_status, missing_paths
from .packs import available_packs


VOICE_STYLE = """
QDialog#voiceSettings { background-color: #fafcfb; }
QWidget { color: #1c3837; font-family: 'Microsoft YaHei UI', sans-serif; font-size: 13px; }
QLabel, QWidget#voicePaths { background: transparent; padding: 0; border: none; }
QLabel#voiceTitle { font-size: 20px; font-weight: bold; }
QLabel#voiceHint, QLabel#volumeValue { color: #4a6361; }
QLineEdit, QComboBox, QPushButton { background: #ffffff; border: 1px solid #becfca;
    border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #edf6f2; border-color: #6b9e92; }
QPushButton:pressed { background: #dceee7; }
QPushButton#voicePreview { background: #256960; color: white; border-color: #256960; }
QPushButton#voicePreview:hover { background: #1a584f; }
QToolButton { color: #375a55; background: transparent; border: none; padding: 4px 0; }
QToolButton:hover { color: #143f38; }
QSlider { background: transparent; min-height: 24px; }
QSlider::groove:horizontal { height: 5px; border-radius: 2px; background: #cbdad5; }
QSlider::sub-page:horizontal { background: #398578; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px;
    background: #256960; }
"""


def settings_dialog(parent, values, volume=100, *, enabled=False, packs_dir=None):
    dialog = QDialog(parent)
    dialog.setObjectName('voiceSettings')
    dialog.setWindowTitle('语音设置')
    dialog.setMinimumWidth(380)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    apply_light_palette(dialog)
    dialog.setStyleSheet(VOICE_STYLE)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 18)
    layout.setSpacing(14)

    heading = QHBoxLayout()
    avatar = QLabel()
    avatar.setPixmap(application_icon().pixmap(48, 48))
    heading.addWidget(avatar)
    titles = QVBoxLayout()
    title = QLabel('天依的声音')
    title.setObjectName('voiceTitle')
    titles.addWidget(title)
    missing = missing_paths(values)
    hint = QLabel(installation_status(values) if missing else '开启朗读后，桌宠每次启动都会提前准备声音。')
    hint.setObjectName('voiceHint')
    hint.setWordWrap(True)
    titles.addWidget(hint)
    heading.addLayout(titles, 1)
    layout.addLayout(heading)

    controls = QHBoxLayout()
    label = QLabel('朗读音量')
    loudness = QSlider(Qt.Orientation.Horizontal)
    loudness.setAccessibleName('朗读音量')
    loudness.setRange(0, 100)
    loudness.setValue(volume)
    label.setBuddy(loudness)
    controls.addWidget(label)
    controls.addWidget(loudness, 1)
    value_label = QLabel(f'{volume}%')
    value_label.setObjectName('volumeValue')
    value_label.setMinimumWidth(38)
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    loudness.valueChanged.connect(lambda value: value_label.setText(f'{value}%'))
    controls.addWidget(value_label)
    layout.addLayout(controls)

    advanced = QToolButton()
    advanced.setCheckable(True)
    advanced.setText('高级设置')
    advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    layout.addWidget(advanced, 0, Qt.AlignmentFlag.AlignLeft)
    fields = QWidget()
    fields.setObjectName('voicePaths')
    form = QFormLayout(fields)
    form.setContentsMargins(0, 0, 0, 0)
    edits = []
    for label, value, directory in (('Python', values[0], False), ('引擎文件夹', values[1], True),
                                    ('声音配置', values[2], False)):
        row = QHBoxLayout()
        edit = QLineEdit(value)
        button = QPushButton('浏览')
        def browse(checked=False, field=edit, is_dir=directory):
            result = (QFileDialog.getExistingDirectory(dialog, '选择文件夹', field.text()) if is_dir
                      else QFileDialog.getOpenFileName(dialog, '选择文件', field.text())[0])
            if result:
                field.setText(result)
        button.clicked.connect(browse)
        row.addWidget(edit)
        row.addWidget(button)
        form.addRow(label, row)
        edits.append(edit)
    layout.addWidget(fields)
    if packs_dir is not None:
        packs_dir = Path(packs_dir)
        row = QHBoxLayout()
        row.addWidget(QLabel('语音包'))
        packs = QComboBox()
        packs.setAccessibleName('选择语音包')
        row.addWidget(packs, 1)
        folder = QPushButton('打开文件夹')
        refresh = QPushButton('刷新')
        row.addWidget(folder)
        row.addWidget(refresh)
        layout.insertLayout(1, row)
        pack_hint = QLabel('把语音包 ZIP 放进文件夹，就可以在这里选择和试听。')
        pack_hint.setWordWrap(True)
        pack_hint.setObjectName('voiceHint')
        layout.insertWidget(2, pack_hint)
        watcher = QFileSystemWatcher(dialog)

        def list_packs():
            try:
                packs_dir.mkdir(parents=True, exist_ok=True)
                found = available_packs(packs_dir)
            except OSError as exc:
                pack_hint.setText(f'无法读取语音包文件夹：{exc}')
                return
            if not watcher.directories():
                watcher.addPath(str(packs_dir))
            current = edits[2].text().strip()
            packs.blockSignals(True)
            packs.clear()
            for path in found:
                packs.addItem(path.stem, str(path))
            index = packs.findData(current)
            if index < 0:
                if found and not Path(current).is_file():
                    index = 0
                    edits[2].setText(packs.itemData(index))
                else:
                    packs.addItem('当前声音配置' if Path(current).is_file() else '尚未添加语音包', current)
                    index = packs.count() - 1
            packs.setCurrentIndex(index)
            packs.blockSignals(False)

        def choose_pack(index):
            if index >= 0:
                edits[2].setText(packs.itemData(index))
                hint.setText(installation_status(tuple(e.text() for e in edits)))

        packs.currentIndexChanged.connect(choose_pack)
        edits[2].editingFinished.connect(list_packs)
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(packs_dir))))
        watcher.directoryChanged.connect(lambda _: list_packs())
        refresh.clicked.connect(list_packs)
        list_packs()
    def expand(opened):
        fields.setVisible(opened)
        advanced.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        dialog.adjustSize()
    advanced.toggled.connect(expand)
    advanced.setChecked(bool(missing))
    expand(bool(missing))

    actions = QHBoxLayout()
    preview = QPushButton('试听' if enabled else '开启并试听')
    preview.setObjectName('voicePreview')
    actions.addWidget(preview)
    actions.addStretch()
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    actions.addWidget(buttons)
    layout.addLayout(actions)

    audition = False
    def accept(with_preview=False):
        nonlocal audition
        paths = tuple(edit.text().strip() for edit in edits)
        if missing_paths(paths):
            advanced.setChecked(True)
            QMessageBox.warning(dialog, '语音设置', installation_status(paths))
            return
        audition = with_preview
        dialog.accept()
    preview.clicked.connect(lambda: accept(True))
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    dialog.adjustSize()
    result = None
    if dialog.exec() == QDialog.DialogCode.Accepted:
        result = tuple(edit.text().strip() for edit in edits) + (loudness.value(), audition)
    dialog.deleteLater()
    return result
