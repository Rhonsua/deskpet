"""Non-blocking collection import using the existing Bilibili browser account."""
import threading
import uuid

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QLabel, QListWidget, QListWidgetItem)

from .bilibili_import import BilibiliImport, ImportCancelled, Source
from .bilibili_account import decode_cookie
from deskpet.ui.theme import apply_light_palette


class ImportSignals(QObject):
    done = Signal(int, object, str)
    progress = Signal(int, str)


class ImportJob(QRunnable):
    def __init__(self, ticket, value, cookie):
        super().__init__()
        self.ticket, self.value, self.cookie = ticket, value, cookie
        self.stopped = threading.Event()
        self.signals = ImportSignals()

    def run(self):
        result, error = None, ''
        try:
            client = BilibiliImport(self.cookie, self.stopped,
                                   lambda text: self.signals.progress.emit(self.ticket, text))
            result = client.read(self.value)
        except ImportCancelled:
            return
        except ValueError as exc:
            error = str(exc)
        except Exception:
            error = 'B站列表格式发生变化，暂时无法读取；原有歌单没有变化。'
        finally:
            self.cookie = ''
            self.signals.done.emit(self.ticket, result, error)


class ImportService(QObject):
    ready = Signal(object, str)
    progress = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ticket, self.active, self.jobs = 0, False, {}

    def start(self, value, cookie=''):
        self.cancel()
        self.active = True
        job = ImportJob(self.ticket, value, cookie)
        self.jobs[self.ticket] = job
        job.signals.done.connect(self.finish)
        job.signals.progress.connect(self.report)
        QThreadPool.globalInstance().start(job)

    def report(self, ticket, message):
        if self.active and ticket == self.ticket:
            self.progress.emit(message)

    def finish(self, ticket, result, error):
        self.jobs.pop(ticket, None)
        if self.active and ticket == self.ticket:
            self.active = False
            self.ready.emit(result, error)

    def cancel(self):
        self.ticket += 1
        self.active = False
        for job in self.jobs.values():
            job.stopped.set()


class BilibiliImportDialog(QDialog):
    def __init__(self, player):
        super().__init__(player)
        self.player, self.settings = player, player.settings
        self.setWindowTitle('B站 · 导入合集与收藏夹')
        self.resize(690, 520)
        apply_light_palette(self)
        self.setStyleSheet('''QDialog {background:#F4F8FA; color:#142B36;}
            QLabel {color:#142B36; background:transparent;}
            QLineEdit,QListWidget {background:white; color:#142B36; border:1px solid #AFC8D3; border-radius:6px; padding:7px;}
            QPushButton {background:white; color:#142B36; border:1px solid #AFC8D3; border-radius:6px; padding:8px;}
            QPushButton:hover {background:#E3F4FC;} QPushButton:disabled {color:#81929A;}
            QListWidget::item {padding:8px;} QListWidget::item:selected {background:#D2EDF8; color:#142B36;}''')
        self.service = ImportService(self)
        self.service.ready.connect(self.loaded)
        self.service.progress.connect(self.set_status)
        self.account_request = ''
        self.pending_source = None
        self.waiting_login = False
        self.player.accountReady.connect(self.account_ready)
        self.account_timeout = QTimer(self)
        self.account_timeout.setSingleShot(True)
        self.account_timeout.timeout.connect(self.account_failed)
        layout = QVBoxLayout(self)
        notice = QLabel('粘贴合集、收藏夹或多 P 视频链接，直接加入 B站歌单。\n也可填写 UP 主主页 / UID，选择其中的合集或收藏夹。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('粘贴 B站链接 / 分享文字 / UP 主 UID')
        self.input.returnPressed.connect(self.read_link)
        row.addWidget(self.input, 1)
        self.read_button = QPushButton('读取并添加')
        self.read_button.clicked.connect(self.read_link)
        row.addWidget(self.read_button)
        layout.addLayout(row)
        account_row = QHBoxLayout()
        self.mine_button = QPushButton('我的收藏夹')
        self.mine_button.clicked.connect(self.read_mine)
        account_row.addWidget(self.mine_button)
        self.login_button = QPushButton('打开 B站网页登录')
        self.login_button.clicked.connect(self.login)
        account_row.addWidget(self.login_button)
        layout.addLayout(account_row)
        self.account_label = QLabel('直接使用桌宠 B站播放网页的账号，无需再次绑定。')
        self.account_label.setTextFormat(Qt.TextFormat.PlainText)
        self.account_label.setWordWrap(True)
        layout.addWidget(self.account_label)
        self.lists = QListWidget()
        self.lists.itemDoubleClicked.connect(lambda _: self.add_selected())
        self.lists.currentRowChanged.connect(lambda _: self.add_button.setEnabled(
            not self.service.active and not self.account_request and self.lists.currentRow() >= 0))
        layout.addWidget(self.lists, 1)
        self.status = QLabel('公开列表无需登录；私密收藏夹需登录本人账号。导入不会打断正在播放的音乐。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.add_button = QPushButton('一键添加选中列表')
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.add_selected)
        buttons.addWidget(self.add_button)
        self.cancel_button = QPushButton('取消读取')
        self.cancel_button.clicked.connect(self.cancel_read)
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)
        close = QPushButton('完成')
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def set_status(self, text):
        self.status.setText(text)

    def busy(self, value):
        for widget in (self.read_button, self.mine_button, self.input):
            widget.setEnabled(not value)
        self.add_button.setEnabled(not value and self.lists.currentRow() >= 0)
        self.cancel_button.setEnabled(value)

    def start_read(self, value):
        if self.service.active or self.account_request:
            return
        self.fetch_account(value)

    def fetch_account(self, value, login=False):
        self.cancel_account()
        self.pending_source = value
        self.waiting_login = login
        self.account_request = uuid.uuid4().hex
        self.busy(True)
        self.account_timeout.start(610000 if login else 30000)
        self.set_status('请在 B站网页完成登录，随后自动读取收藏夹；也可点“我的收藏夹”重新检测。' if login
                        else '正在读取桌宠 B站网页的登录状态…')
        if login:
            self.mine_button.setEnabled(True)
        self.player.request_import_account(self.account_request, login=login)

    def cancel_account(self):
        if self.account_request:
            self.player.cancel_import_account(self.account_request)
        self.account_request = ''
        self.pending_source = None
        self.account_timeout.stop()

    def account_ready(self, event):
        if not self.account_request or event.get('request') != self.account_request:
            return
        value = self.pending_source
        self.cancel_account()
        if event.get('error'):
            if not (isinstance(value, Source) and value.kind == 'mine'):
                self.set_status('暂未接回网页登录状态，先尝试读取公开列表…')
                self.service.start(value)
                return
            self.busy(False)
            self.set_status(event['error'])
            return
        if event.get('login_required') and isinstance(value, Source) and value.kind == 'mine':
            self.fetch_account(value, login=True)
            return
        try:
            cookie = decode_cookie(event['protected']) if event.get('protected') else ''
        except (ValueError, TypeError):
            self.busy(False)
            self.set_status('未能接回网页登录状态，请重新打开 B站网页后再读取。')
            return
        self.set_status('正在后台读取 B站列表…')
        self.service.start(value, cookie)

    def account_failed(self):
        value = self.pending_source
        self.cancel_account()
        if value is not None and not (isinstance(value, Source) and value.kind == 'mine'):
            self.set_status('网页登录状态读取超时，先尝试读取公开列表…')
            self.service.start(value)
            return
        self.busy(False)
        self.set_status('读取网页登录状态超时，请关闭 B站网页后重新读取。')

    def read_link(self):
        if self.input.text().strip():
            self.start_read(self.input.text())
        else:
            self.set_status('请先粘贴链接，或点击“我的收藏夹”。')

    def read_mine(self):
        if self.waiting_login and self.account_request:
            self.fetch_account(Source('mine'))
        else:
            self.start_read(Source('mine'))

    def add_selected(self):
        item = self.lists.currentItem()
        if item:
            self.start_read(item.data(Qt.ItemDataRole.UserRole))

    def loaded(self, result, error):
        self.busy(False)
        if error:
            self.set_status(error)
            return
        if not isinstance(result, dict):
            return
        if 'choices' in result:
            if 'account' in result:
                self.account_label.setText('B站网页当前账号：' + result['account'])
            self.lists.clear()
            labels = {'season':'合集', 'series':'系列', 'favorite':'收藏夹', 'uploads':'投稿'}
            for choice in result['choices']:
                source, count = choice['source'], choice['count']
                item = QListWidgetItem(f"[{labels[source.kind]}] {choice['title']}" + (f'  ·  {count} 个视频' if count is not None else ''))
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.lists.addItem(item)
            self.set_status((f'找到 {self.lists.count()} 个列表，选择后点击“一键添加选中列表”。' if self.lists.count()
                             else '没有找到可读取的收藏夹或合集。可以直接粘贴具体列表链接。') + ('\n' + result['warning'] if result.get('warning') else ''))
            return
        added, repeated = self.player.add_imported_tracks(result.get('tracks', []))
        message = f"《{result.get('title', '列表')}》已添加 {added} 首，跳过 {repeated} 首重复视频"
        if result.get('skipped'):
            message += f"、{result['skipped']} 个失效或非视频项目"
        if not result.get('tracks'):
            message = '这个列表里没有可导入的视频，可能为空或内容已失效；原有歌单没有变化'
        self.set_status(message + '。')
        self.player.note.setText(message + '。')

    def cancel_read(self):
        self.cancel_account()
        self.service.cancel()
        self.busy(False)
        self.set_status('读取已取消，原有歌单没有变化。')

    def login(self):
        self.cancel_read()
        self.fetch_account(Source('mine'), login=True)

    def shutdown(self):
        self.service.cancel()
        self.cancel_account()
        self.busy(False)

    def done(self, result):
        self.shutdown()
        super().done(result)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
