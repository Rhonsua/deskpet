"""Isolated Qt HTTP runtime. No widgets, model renderer, user files or key logs."""
import json
import sys
import threading
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager
from pet_chat.config import ProviderConfig
from pet_chat.client import ChatClient as HttpTransport


def emit(event):
    sys.stdout.write('TIANYI_CHAT ' + json.dumps(event, ensure_ascii=False) + '\n')
    sys.stdout.flush()


class Worker(QObject):
    command = Signal(object)

    def __init__(self):
        super().__init__()
        self.transport = HttpTransport(self)
        self.transport.manager = QNetworkAccessManager(self.transport)
        self.active = None
        self.latest = ''
        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.timeout.connect(self.flush)
        self.transport.partial.connect(self.partial)
        self.transport.completed.connect(lambda text: self.finish('completed', text))
        self.transport.failed.connect(lambda text: self.finish('failed', text))
        self.command.connect(self.handle)

    @Slot(object)
    def handle(self, command):
        if command is None:
            self.transport.cancel()
            QCoreApplication.quit()
            return
        if not isinstance(command, dict):
            return
        if command.get('cmd') == 'cancel':
            if command.get('id') == self.active:
                self.transport.cancel()
                self.flush_timer.stop()
                self.active = None
                self.latest = ''
            return
        if command.get('cmd') != 'start':
            return
        self.transport.cancel()
        self.flush_timer.stop()
        self.active, self.latest = command.get('id'), ''
        try:
            self.transport.start(ProviderConfig(**command['config']), command['messages'],
                                 test=command.get('test', False))
        except (ValueError, TypeError, KeyError):
            self.finish('failed', '聊天配置无效，请检查接口地址和模型。')

    def partial(self, text):
        self.latest = text
        if not self.flush_timer.isActive():
            self.flush_timer.start(50)

    def flush(self):
        if self.active is not None:
            emit(dict(type='partial', id=self.active, text=self.latest))

    def finish(self, kind, text):
        self.flush_timer.stop()
        active, self.active = self.active, None
        self.latest = ''
        if active is not None:
            emit(dict(type=kind, id=active, text=text))


def run():
    app = QCoreApplication(sys.argv)
    worker = Worker()

    def read_commands():
        try:
            while True:
                line = sys.stdin.buffer.readline(256 * 1024)
                if not line or not line.endswith(b'\n'):
                    break
                try:
                    command = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                worker.command.emit(command)
        finally:
            worker.command.emit(None)

    threading.Thread(target=read_commands, daemon=True).start()
    emit(dict(type='ready'))
    app.exec()


if __name__ == '__main__':
    run()
