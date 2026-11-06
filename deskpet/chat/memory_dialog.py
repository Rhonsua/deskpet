"""User-visible controls for the local, per-character memory bank."""
import sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QMessageBox,
                               QAbstractItemView)


class MemoryDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        from deskpet.ui.theme import apply_light_palette
        apply_light_palette(self)
        self.setStyleSheet('''
            QDialog { background: #F2F7FA; color: #142B36; }
            QLabel, QCheckBox { background: transparent; color: #142B36; }
            QListWidget { background: #FFFFFF; color: #142B36; border: 1px solid #B1CBD7;
                          border-radius: 6px; padding: 5px; }
            QListWidget::item { padding: 7px 5px; border-bottom: 1px solid #E2EDF2; }
            QListWidget::item:selected { background: #D3EAF5; color: #142B36; }
        ''')
        self.window = window
        self.bank = window.store.memories
        self.character = window.character
        self.setWindowTitle(window.name + ' · 自动记忆')
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        self.toggle = QCheckBox('自动记忆与相关旧话题回忆（不额外调用 API）')
        self.toggle.setChecked(self.bank.enabled(self.character))
        self.toggle.toggled.connect(self.set_enabled)
        layout.addWidget(self.toggle)
        notice = QLabel('只从你说的话中保留明确偏好和部分生活原话，按角色分别保存。\n'
                        '每次只发送少量相关记忆；关闭后不再新增或使用自动记忆。\n'
                        '删除此处记录不会删除聊天和手动记忆，最近对话仍可能提到同一件事。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.rows = QListWidget()
        self.rows.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rows.setWordWrap(True)
        layout.addWidget(self.rows, 1)
        buttons = QHBoxLayout()
        remove = QPushButton('删除选中记忆')
        remove.clicked.connect(self.remove_selected)
        buttons.addWidget(remove)
        clear = QPushButton('清空自动记忆')
        clear.clicked.connect(self.clear)
        buttons.addWidget(clear)
        close = QPushButton('关闭')
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        from .memory import local_time
        self.rows.clear()
        for row in self.bank.records(self.character):
            title = '称呼 / 偏好' if row['kind'] == 'fact' else '旧话题'
            when = local_time(row['created'])[:16].replace('T', ' ')
            item = QListWidgetItem(f'{title} · {when}\n{row["content"]}')
            item.setData(Qt.ItemDataRole.UserRole, row['id'])
            self.rows.addItem(item)

    def change(self, operation):
        # A response already in flight may contain a now-deleted memory.
        self.window.stop()
        try:
            operation()
            self.refresh()
        except sqlite3.Error:
            QMessageBox.warning(self, '记忆保存失败', '没有完成这次修改，请检查磁盘空间后重试。')

    def set_enabled(self, enabled):
        self.change(lambda: self.bank.set_enabled(self.character, enabled))
        self.toggle.blockSignals(True)
        self.toggle.setChecked(self.bank.enabled(self.character))
        self.toggle.blockSignals(False)

    def remove_selected(self):
        ids = [row.data(Qt.ItemDataRole.UserRole) for row in self.rows.selectedItems()]
        if ids:
            self.change(lambda: self.bank.delete(self.character, ids))

    def clear(self):
        if QMessageBox.question(self, '清空自动记忆', '清空当前角色的自动记忆？\n'
                '聊天记录和手动记忆保留，旧记录不会被重新导入。') == QMessageBox.StandardButton.Yes:
            self.change(lambda: self.bank.clear(self.character))
