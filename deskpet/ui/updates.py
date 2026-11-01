"""Optional background release checks; downloading and installation need user clicks."""
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QVBoxLayout)

from deskpet.paths import PROJECT_ROOT
from deskpet.runtime.updates import (Cancelled, RELEASES_URL, UpdateError,
                                     download_release, fetch_latest)
from deskpet.version import VERSION


CHECK_INTERVAL = 12 * 60 * 60


class UpdateController(QObject):
    completed = Signal(str, object, str)
    download_progress = Signal(object, object)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.settings = panel.settings
        self.directory = Path(panel.data_dir) / 'updates'
        self.closed = False
        self.started = False
        self.job = ''
        self.manual = False
        self.last_manual = 0.
        self.cancel = threading.Event()
        self.release = None
        self.ready = None
        self.dialog = None
        self.progress = None
        self.installable = (os.name == 'nt' and bool(getattr(sys, 'frozen', False))
                            and (PROJECT_ROOT / 'installed-files.txt').is_file())
        self.completed.connect(self.finish)
        self.download_progress.connect(self.show_progress)
        panel.update_check.clicked.connect(lambda: self.check(manual=True))
        panel.update_toggle.toggled.connect(self.set_enabled)
        panel.update_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.poll = QTimer(self)
        self.poll.setInterval(60 * 60 * 1000)
        self.poll.timeout.connect(self.check)
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.timeout.connect(self.check)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def start(self):
        self.started = True
        if self.panel.update_toggle.isChecked():
            self.poll.start()
            self.delay.start(30000)  # Keep network setup off the initial loading path.

    def set_enabled(self, enabled):
        self.settings.setValue('updates/auto_check', enabled)
        self.poll.stop()
        self.delay.stop()
        if enabled and self.started:
            self.poll.start()
            self.delay.start(30000)

    def note(self, text):
        self.panel.update_note.setText(f'当前版本 {VERSION} · {text}')

    def launch_job(self, kind, operation):
        self.job = kind
        self.cancel = threading.Event()
        cancel = self.cancel

        def run():
            try:
                result, error = operation(cancel), ''
            except Cancelled:
                result, error = None, ''
            except Exception as exc:
                result = None
                error = str(exc) if isinstance(exc, UpdateError) else '更新未完成，请稍后重试。'
            try:
                self.completed.emit(kind, result, error)
            except RuntimeError:
                pass  # App closed while the network request was unwinding.

        threading.Thread(target=run, name='TianyiUpdate', daemon=True).start()

    def check(self, manual=False):
        if self.closed:
            return
        if self.job:
            if manual and self.job == 'check':
                self.manual = True
            if manual and self.progress:
                self.progress.show()
                self.progress.raise_()
            return
        if self.dialog:
            if manual:
                self.dialog.show()
                self.dialog.raise_()
            return
        if manual and self.ready and self.ready.is_file():
            self.offer_install()
            return
        now = time.time()
        if not manual:
            if not self.panel.update_toggle.isChecked():
                return
            try:
                elapsed = now - float(self.settings.value('updates/last_check', 0))
            except (TypeError, ValueError):
                elapsed = CHECK_INTERVAL
            if 0 <= elapsed < CHECK_INTERVAL:
                return
        elif time.monotonic() - self.last_manual < 5:
            return
        self.last_manual = time.monotonic()
        self.manual = manual
        self.settings.setValue('updates/last_check', now)
        self.note('正在检查新版本…')
        self.launch_job('check', fetch_latest)

    def finish(self, kind, result, error):
        if self.closed or kind != self.job:
            return
        self.job = ''
        if self.progress:
            self.progress.blockSignals(True)  # Programmatic close is not user cancellation.
            self.progress.close()
            self.progress.deleteLater()
            self.progress = None
        if self.cancel.is_set():
            self.note('已取消下载，可随时重新检查')
            return
        if error:
            self.note(error)
            if kind == 'download':
                box = QMessageBox(self.panel)
                self.dialog = box
                box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                box.setWindowTitle('更新下载未完成')
                box.setTextFormat(Qt.TextFormat.PlainText)
                box.setText(error)
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
                box.finished.connect(lambda _: setattr(self, 'dialog', None))
                box.show()
            return  # Automatic failures never interrupt the pet or other windows.
        if kind == 'download':
            self.ready = result
            self.note('新版已下载，点击“检查更新”可打开安装程序')
            self.offer_install()
            return
        self.release = result
        if result is None:
            self.note('暂未发现可用的新版本')
            return
        self.note(f'发现新版本 {result.version}')
        if (self.manual or (self.panel.update_toggle.isChecked()
                            and self.settings.value('updates/skipped_version', '') != result.version)):
            self.offer_release(result)

    def offer_release(self, release):
        dialog = QDialog(self.panel)
        self.dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle('天依桌宠 · 发现新版本')
        dialog.resize(500, 370)
        layout = QVBoxLayout(dialog)
        heading = QLabel(f'{VERSION} → {release.version}　安装包约 {release.size / 1024 ** 2:.1f} MB')
        layout.addWidget(heading)
        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.notes)  # Release notes are display data, never HTML/scripts.
        layout.addWidget(notes)
        hint = QLabel('确认后下载；完成后可选择退出桌宠并打开安装程序。'
                      if self.installable else '当前为源码或免安装运行，可前往发行页下载并选择安装位置。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        skip = QPushButton('跳过此版本')
        later = QPushButton('稍后再说')
        update = QPushButton('下载更新' if self.installable else '打开下载页')
        for button in (skip, later, update):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        def skipped():
            self.settings.setValue('updates/skipped_version', release.version)
            dialog.close()

        def accepted():
            dialog.close()
            if self.installable:
                self.download(release)
            else:
                QDesktopServices.openUrl(QUrl(release.page_url))

        skip.clicked.connect(skipped)
        later.clicked.connect(dialog.close)
        update.clicked.connect(accepted)
        dialog.finished.connect(lambda _: setattr(self, 'dialog', None))
        dialog.show()  # Nonmodal: an automatic notice cannot block a running task.

    def download(self, release):
        if self.closed or self.job:
            return
        self.release = release
        self.ready = None
        progress = QProgressDialog('正在连接 GitHub…', '取消下载', 0, 100, self.panel)
        self.progress = progress
        progress.setWindowTitle(f'下载天依桌宠 {release.version}')
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.canceled.connect(lambda: self.cancel.set())
        self.note('正在下载更新，桌宠可以继续使用')
        self.launch_job('download', lambda cancel: download_release(
            release, self.directory, cancel, self.download_progress.emit))
        progress.show()

    def show_progress(self, received, total):
        if not self.closed and self.job == 'download' and self.progress and not self.cancel.is_set():
            self.progress.setLabelText(f'正在下载：{received / 1024 ** 2:.1f} / {total / 1024 ** 2:.1f} MB')
            self.progress.setValue(min(99, received * 100 // max(1, total)))

    def offer_install(self):
        if not self.ready or not self.installable:
            return
        box = QMessageBox(self.panel)
        self.dialog = box
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.setWindowTitle('天依桌宠 · 更新已就绪')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText('新版已下载并通过校验。现在退出桌宠并打开安装程序？')
        box.setInformativeText('退出会停止当前播放和工作任务。设置、歌单、聊天记录会保留。\n'
                               f'安装时请选择原来的位置：\n{PROJECT_ROOT}')
        install = box.addButton('退出并打开安装程序', QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton('稍后安装', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(later)
        box.setEscapeButton(later)

        def chosen(button):
            if button is install:
                try:
                    os.startfile(str(self.ready))
                except OSError:
                    self.note('无法打开安装程序，可从更新目录手动运行或重新下载。')
                    return
                QApplication.instance().quit()

        box.buttonClicked.connect(chosen)
        box.finished.connect(lambda _: setattr(self, 'dialog', None))
        box.show()

    def shutdown(self):
        self.closed = True
        self.cancel.set()
        self.poll.stop()
        self.delay.stop()
