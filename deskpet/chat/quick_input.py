"""A small composer sharing the existing companion conversation and client."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel


class QuickChatInput(QWidget):
    def __init__(self, pet, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.window = None
        self.pending_text = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.input = QLineEdit()
        self.input.setPlaceholderText('和我聊天…')
        self.input.setAccessibleName('陪伴模式快捷消息')
        self.input.setMaxLength(4000)
        self.input.setMinimumWidth(130)
        self.input.setStyleSheet('QLineEdit { border: 1px solid #AFC8D3; border-radius: 4px; padding: 6px; }')
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input, 1)
        self.send_button = QPushButton('发送')
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        self.input.textChanged.connect(self.update_send)
        self.update_send()

    def bind(self):
        window = self.pet.ensure_chat()
        if window is not None and window is not self.window:
            self.window = window
            window.busyChanged.connect(self.update_busy)
            window.quickMessageFinished.connect(self.finished)
        return window

    def update_send(self):
        self.send_button.setEnabled(bool(self.input.text().strip()) and not self.input.isReadOnly())

    def update_busy(self, busy):
        self.input.setReadOnly(busy)
        self.update_send()

    def show_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def send(self):
        text = self.input.text().strip()
        if not text or self.pending_text:
            return
        window = self.bind()
        if window is None:
            self.show_status('聊天暂时无法打开，请检查数据目录。')
            return
        if window.pending or window.testing:
            self.show_status('正在回复，请稍等。可在“和我聊天”中停止。')
            return
        self.pet.stop_roaming()
        self.pending_text = text
        self.input.clear()
        self.show_status('正在回复…')
        self.update_busy(True)
        if not window.send_message(text=text) and self.pending_text:
            self.finished(window.status.text(), False)

    def finished(self, message, success):
        if not self.pending_text:
            return
        if not success:
            self.input.setText(self.pending_text)
        self.pending_text = ''
        self.update_busy(False)
        self.show_status('' if success else message + ' 可点“和我聊天”查看设置或重试。')

    def showEvent(self, event):
        super().showEvent(event)
        window = getattr(self.pet, 'chat_window', None)
        if window is not None:
            self.bind()
            self.update_busy(bool(window.pending or window.testing))
