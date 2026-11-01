"""One music window with independently retained provider pages."""
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget


class MusicPlatformWidget(QWidget):
    providerChanged = Signal(str)
    widgetCreated = Signal(str, object)

    def __init__(self, data_dir, parent=None, *, factories=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.widgets = {}
        self._factories = factories or {}
        self._current_provider = ''
        self._closed = False
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel('音乐平台'))
        self.provider_choice = QComboBox()
        self.provider_choice.addItem('网易云', 'netease')
        self.provider_choice.addItem('酷狗', 'kugou')
        row.addWidget(self.provider_choice)
        row.addStretch()
        layout.addLayout(row)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.provider_choice.currentIndexChanged.connect(self._choice_changed)
        self.set_provider('netease')

    @property
    def current_provider(self):
        return self._current_provider

    @property
    def current_widget(self):
        return self.widgets.get(self._current_provider)

    def ensure_provider(self, key):
        if key not in ('netease', 'kugou'):
            raise ValueError('未知音乐平台')
        if key not in self.widgets:
            if self._closed:
                raise RuntimeError('音乐窗口已关闭')
            factory = self._factories.get(key)
            if factory is None:
                if key == 'netease':
                    from ..netease.widget import NeteaseWidget
                    factory = NeteaseWidget
                else:
                    from ..kugou.widget import KugouWidget
                    factory = KugouWidget
            directory = self.data_dir if key == 'netease' else self.data_dir.parent / 'kugou'
            widget = factory(directory, self)
            self.widgets[key] = widget
            self.stack.addWidget(widget)
            self.widgetCreated.emit(key, widget)
        return self.widgets[key]

    def _choice_changed(self, index):
        self.set_provider(self.provider_choice.itemData(index))

    def set_provider(self, key):
        widget = self.ensure_provider(key)
        if key == self._current_provider:
            return widget
        previous = self.current_widget
        if previous is not None:
            previous.cancel()
        self._current_provider = key
        self.stack.setCurrentWidget(widget)
        index = self.provider_choice.findData(key)
        self.provider_choice.blockSignals(True)
        self.provider_choice.setCurrentIndex(index)
        self.provider_choice.blockSignals(False)
        self.providerChanged.emit(key)
        return widget

    def cancel(self):
        for widget in self.widgets.values():
            widget.cancel()

    def shutdown(self):
        if not self._closed:
            self._closed = True
            for widget in self.widgets.values():
                widget.shutdown()

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)
