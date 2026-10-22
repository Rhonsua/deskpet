"""One opt-in pre-play beat preparation, with reusable analysis and cancel guards."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QLabel, QProgressDialog

from netease_music.downloads import Downloader


class MusicPreparation(QObject):
    def __init__(self, companion):
        super().__init__(companion)
        self.companion, self.beats = companion, companion.beats
        self.panel = companion.pet.panel
        self.transfer = Downloader(self)
        self.transfer.completed.connect(self._downloaded)
        self.transfer.failed.connect(lambda message: self._complete(False))
        self.transfer.progress.connect(self._progress)
        self.beats.analysisFinished.connect(self._analyzed)
        self.beats.changed.connect(self._settings_changed)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self._complete(False))
        self.pending = False
        self.callback = self.dialog = self.temp = None
        self.identity = ''
        self.analyzing = False

    def local(self, path, callback):
        self.cancel()
        if not self.beats.enabled:
            callback()
            return
        self.beats.set_source('local:' + str(Path(path).absolute()))
        if self.beats.has_timing():
            callback()
            return
        self.beats.cancel()
        self._begin(callback, '首次分析这首歌的节拍，完成后自动播放…')
        self.analyzing = True
        self.beats.analyze()

    def online(self, item, media, callback):
        self.cancel()
        if not self.beats.enabled or media.get('trial'):
            callback()
            return
        source = 'netease:' + item['id']
        identity = json.dumps([item['id'], media.get('size', 0), media.get('duration_ms', 0),
                               media.get('extension', '')], separators=(',', ':'))
        self.beats.restore_online(source, identity)
        if self.beats.has_timing():
            callback()
            return
        self.identity = identity
        self._begin(callback, '首次准备这首歌的节拍，完成后自动播放…\n以后会复用解析结果。')
        try:
            root = (self.companion.root / 'beat-work').resolve()
            root.mkdir(parents=True, exist_ok=True)
            self.temp = tempfile.TemporaryDirectory(prefix='analysis-', dir=root)
            Path(self.temp.name).resolve().relative_to(root)
            # This is temporary analysis of the normal playable stream, never
            # an exported download or a fallback for denied download rights.
            self.transfer.start(media['url'], self.temp.name, 'analysis', media['extension'],
                                expected_size=media.get('size', 0))
        except (OSError, ValueError):
            self._complete(False)

    def _begin(self, callback, message):
        self.pending, self.callback = True, callback
        self.dialog = QProgressDialog('', '跳过分析，直接播放', 0, 0, self.panel)
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        self.dialog.setLabel(label)
        self.dialog.setLabelText(message)
        self.dialog.setWindowTitle('准备歌曲节拍')
        self.dialog.setMinimumDuration(0)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.canceled.connect(lambda: self._complete(False))
        self.dialog.show()
        self.timeout.start(180000)
        self.panel.status.setText(message.split('\n')[0])

    def _progress(self, received, total):
        if self.pending and self.dialog:
            amount = f'{received * 100 // total}%' if total else f'{received / 1048576:.1f} MiB'
            self.dialog.setLabelText('首次准备节拍：' + amount + '\n准备完成后自动播放，以后复用结果。')

    def _downloaded(self, path, _):
        if not self.pending:
            return
        self.dialog.setLabelText('正在解析节拍，完成后自动播放…')
        self.analyzing = True
        self.beats.analyze_online(Path(path), self.identity)

    def _analyzed(self, success):
        if self.pending and self.analyzing:
            self._complete(success)

    def _settings_changed(self):
        if self.pending and not self.beats.enabled:
            self._complete(False)

    def _complete(self, success):
        if not self.pending:
            return
        callback = self.callback
        self.cancel()
        if callback is not None:
            callback()
        if not success:
            self.panel.status.setText('本次节拍未就绪，将使用原来的动作。')

    def cancel(self):
        self.pending, self.callback = False, None
        self.timeout.stop()
        self.transfer.cancel()
        if self.analyzing:
            self.analyzing = False
            self.beats.cancel()
        dialog, self.dialog = self.dialog, None
        if dialog:
            dialog.close()
            dialog.deleteLater()
        temporary, self.temp = self.temp, None
        if temporary:
            # Only our verified, per-analysis directory can be removed.
            Path(temporary.name).resolve().relative_to((self.companion.root / 'beat-work').resolve())
            try:
                temporary.cleanup()
            except OSError:
                self.panel.status.setText('节拍准备结束，临时音频清理失败；请检查数据目录权限。')
