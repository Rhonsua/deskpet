"""Optional Mod page, using only Qt widgets already provided by the desktop app."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QPlainTextEdit, QFileDialog)

from .instructions import apply_persona, remove_persona, current_persona, validate_persona


class PersonaWidget(QWidget):
    def __init__(self, mod, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.default = Path(__file__).with_name('persona.md').read_text('utf-8')
        self.saved_text = self.default
        layout = QVBoxLayout(self)
        hint = QLabel('选择与工位相同的项目文件夹，检查人设后点击导入。\n'
                      '导入后在该项目新建工作对话生效；后续修改请在当前任务结束后新建对话。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        self.folder.setPlaceholderText('选择工作项目')
        row.addWidget(self.folder, 1)
        choose = QPushButton('选择项目')
        choose.clicked.connect(self.choose_project)
        row.addWidget(choose)
        layout.addLayout(row)
        self.editor = QPlainTextEdit(self.default)
        self.editor.setMinimumHeight(260)
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        for caption, callback in [('从文件导入', self.load_file), ('恢复内置人设', self.restore_default)]:
            button = QPushButton(caption)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.apply_button = QPushButton('导入到此项目')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        row.addWidget(self.apply_button)
        self.remove_button = QPushButton('移除此项目的天依人设')
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove)
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        note = QLabel('导入位置为所选项目的 AGENTS.local.md。该文件也可能被同项目下的其他 Agent 工具读取。\n'
                      '停用 Mod 后，已导入的人设仍在项目中；可用上方“移除”按钮清除本 Mod 的部分。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        if mod.project:
            self.select_project(mod.project)

    def has_unsaved_changes(self):
        return self.editor.toPlainText() != self.saved_text

    def choose_project(self):
        path = QFileDialog.getExistingDirectory(self, '选择工位对应的项目文件夹', self.folder.text())
        if path:
            self.select_project(path)

    def select_project(self, path):
        try:
            text = current_persona(path)
            self.mod.remember(path)
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        self.folder.setText(self.mod.project)
        # Keep an edited/imported draft while choosing its destination project.
        if not self.has_unsaved_changes():
            self.editor.setPlainText(text if text is not None else self.default)
            self.saved_text = self.editor.toPlainText()
        self.apply_button.setEnabled(True)
        self.remove_button.setEnabled(text is not None)
        self.status.setText('此项目已导入天依人设，可以更新。' if text is not None else '检查人设后即可导入。')

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入工作人设', '', '人设文本 (*.md *.txt)')
        if not path:
            return
        try:
            with Path(path).open('rb') as stream:
                raw = stream.read(48004)
            self.editor.setPlainText(validate_persona(raw.decode('utf-8-sig')))
            self.status.setText('人设已载入预览，点击“导入到此项目”后生效。')
        except (OSError, ValueError) as error:
            self.status.setText('导入失败：' + str(error))

    def restore_default(self):
        self.editor.setPlainText(self.default)
        self.status.setText('已恢复内置预览，点击“导入到此项目”后生效。')

    def apply(self):
        try:
            target = apply_persona(self.folder.text(), self.editor.toPlainText())
        except (OSError, ValueError) as error:
            self.status.setText('导入失败：' + str(error))
            return
        self.saved_text = self.editor.toPlainText()
        self.remove_button.setEnabled(True)
        self.status.setText('已导入 ' + str(target) + '\n请在该项目新建工作对话。')

    def remove(self):
        try:
            removed = remove_persona(self.folder.text())
        except (OSError, ValueError) as error:
            self.status.setText('移除失败：' + str(error))
            return
        self.remove_button.setEnabled(False)
        self.status.setText('已移除天依人设，下次新建工作对话生效。' if removed else '此项目没有本 Mod 导入的人设。')
