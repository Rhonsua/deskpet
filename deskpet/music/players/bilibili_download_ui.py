"""Cancellable download queue, conflict questions and local-library handoff."""
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, QTimer, QStandardPaths, Qt
from PySide6.QtWidgets import QFileDialog, QProgressDialog, QMessageBox, QLabel
from .bilibili_account import decode_cookie
from .bilibili_download import Cancelled, download_mp3, dispose_result, commit_result, target_path
from .bilibili_import import Source
from .bilibili_import_dialog import ImportService


class DownloadSignals(QObject):
    done = Signal(object, str)
    progress = Signal(str)


class DownloadJob(QRunnable):
    def __init__(self, track, directory, cookie, tools_directory):
        super().__init__()
        self.track, self.directory, self.cookie = track, directory, cookie
        self.tools_directory = tools_directory
        self.stopped = threading.Event()
        self.signals = DownloadSignals()

    def run(self):
        result, error = None, ''
        try:
            result = download_mp3(self.track['url'], self.directory, self.cookie, self.stopped,
                                  self.signals.progress.emit, tools_directory=self.tools_directory)
        except Cancelled:
            pass
        except ImportError:
            error = '下载组件缺失，请更新完整桌宠；源码版请安装 requirements.txt。'
        except ValueError as exc:
            error = str(exc)
        except Exception:
            error = '未能下载此音轨，请在 B站网页确认可播放并完成登录或验证后重试。'
        finally:
            self.cookie = ''
            if self.stopped.is_set() and result is not None:
                dispose_result(result, self.directory)
                result = None
            self.signals.done.emit(result, error)


class BilibiliDownloads(QObject):
    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.running = False
        self.completing = False
        self.job = None
        self.cookie = self.account_request = ''
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.account_timeout)
        player.accountReady.connect(self.account_ready)
        self.dialog = None
        self.directory = None
        self.results = []
        self.parts = ImportService(self)
        self.parts.ready.connect(self.parts_ready)
        self.parts.progress.connect(self.set_progress)

    def start(self, tracks, directory=None, *, all_parts=False):
        if self.running or self.job is not None or self.completing:
            if self.dialog is not None:
                self.dialog.show()
                self.dialog.raise_()
            return
        if not tracks:
            self.player.note.setText('请先添加或选中要下载的视频。')
            return
        if directory is None:
            default = self.player.settings.value('bilibili_download_directory', '')
            default = default or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
            directory = QFileDialog.getExistingDirectory(self.player, '选择 B站 MP3 保存文件夹', str(default))
        if not directory:
            return
        if not Path(directory).is_dir():
            self.player.note.setText('保存文件夹不存在。')
            return
        self.directory = Path(directory).resolve()
        self.tracks = [dict(item) for item in tracks]
        self.all_parts = all_parts
        self.index = self.saved = self.failed = self.skipped = 0
        self.results = []
        self.cookie = ''
        self.playlist_id = str(self.player.settings.value('bilibili_download_playlist_id', '') or '')
        self.running = True
        self.player.settings.setValue('bilibili_download_directory', str(self.directory))
        self.dialog = QProgressDialog('', '取消下载', 0, len(self.tracks), self.player.window())
        self.dialog.setWindowTitle('B站 · 下载 MP3')
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.dialog.setLabel(label)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setMinimumDuration(0)
        self.dialog.canceled.connect(self.cancel)
        self.dialog.setValue(0)
        self.dialog.setLabelText('正在读取桌宠 B站网页的登录状态…')
        self.dialog.show()
        self.account_request = uuid.uuid4().hex
        self.timer.start(20000)
        self.player.request_import_account(self.account_request)

    def cancel_account(self):
        self.timer.stop()
        if self.account_request:
            self.player.cancel_import_account(self.account_request)
        self.account_request = ''

    def account_ready(self, event):
        if not self.running or not self.account_request or event.get('request') != self.account_request:
            return
        self.cancel_account()
        try:
            self.cookie = decode_cookie(event['protected']) if event.get('protected') else ''
        except (ValueError, TypeError):
            self.cookie = ''
        self.prepare()

    def account_timeout(self):
        self.cancel_account()
        if self.running:
            self.prepare()  # Public videos remain downloadable without an account.

    def prepare(self):
        if self.all_parts:
            self.dialog.setRange(0, 0)
            self.set_progress('正在读取此视频的全部分 P…')
            self.parts.start(Source('parts', url=self.tracks[0]['url']), self.cookie)
        else:
            self.next()

    def parts_ready(self, result, error):
        if not self.running:
            return
        tracks = (result or {}).get('tracks') or []
        if error or not tracks:
            self.failed = 1
            self.results.append(error or '没有找到可下载的分 P。')
            self.finish()
            return
        self.tracks = tracks
        self.dialog.setRange(0, len(tracks))
        self.next()

    def next(self):
        if not self.running:
            return
        if self.index >= len(self.tracks):
            self.finish()
            return
        self.set_progress('准备下载…')
        self.job = DownloadJob(self.tracks[self.index], self.directory, self.cookie,
                               self.player.owner.data_dir / 'tools')
        self.job.signals.progress.connect(self.set_progress)
        self.job.signals.done.connect(self.completed)
        QThreadPool.globalInstance().start(self.job)

    def set_progress(self, text):
        if self.running and self.dialog is not None:
            track = self.tracks[self.index]
            self.dialog.setLabelText(f'{self.index + 1}/{len(self.tracks)} · {track.get("title") or track["url"]}\n{text}')

    def completed(self, result, error):
        self.job = None
        if not self.running:
            if result:
                dispose_result(result, self.directory)
            return
        if result:
            # The overwrite question spins a nested event loop. Do not let a
            # canceled batch be replaced until its staging file is disposed.
            self.completing = True
            try:
                target = target_path(result, self.directory)
                overwrite = False
                if target.exists():
                    question = QMessageBox(self.player.window())
                    question.setWindowTitle('文件已存在')
                    question.setTextFormat(Qt.TextFormat.PlainText)
                    question.setText(f'已存在 {target.name}\n是否覆盖？选择“否”会跳过这首。')
                    question.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                                QMessageBox.StandardButton.Cancel)
                    question.setDefaultButton(QMessageBox.StandardButton.No)
                    decision = question.exec()
                    if decision == QMessageBox.StandardButton.Cancel:
                        self.cancel()
                    elif decision == QMessageBox.StandardButton.No:
                        self.skipped += 1
                    else:
                        overwrite = True
                    if not self.running or decision != QMessageBox.StandardButton.Yes:
                        return
                if not self.running:
                    return
                path = commit_result(result, self.directory, overwrite=overwrite)
                self.saved += 1
                try:
                    self.add_to_local(path)
                except Exception:
                    self.results.append(f'{path.name}：已保存，但加入歌单失败，可手动导入。')
            except FileExistsError:
                self.skipped += 1
                self.results.append('保存时出现同名文件，已跳过以避免覆盖。')
            except (OSError, ValueError):
                self.failed += 1
                self.results.append('文件保存失败，请检查文件夹空间和权限。')
            finally:
                try:
                    dispose_result(result, self.directory)
                finally:
                    self.completing = False
                    self.advance()
        else:
            self.failed += 1
            self.results.append(error or '下载未完成。')
            self.advance()

    def advance(self):
        if self.running:
            self.index += 1
            self.dialog.setValue(self.index)
            QTimer.singleShot(0, self.next)

    def add_to_local(self, path):
        panel = self.player.owner
        library = panel.library
        playlist = next((p for p in library.playlists if p['id'] == self.playlist_id), None)
        if playlist is None:
            active = library.active_id
            self.playlist_id = library.create('B站下载')
            playlist = library.active
            library.active_id = active
            self.player.settings.setValue('bilibili_download_playlist_id', self.playlist_id)
        value = str(path.resolve())
        if value not in playlist['paths']:
            playlist['paths'].append(value)
        if not panel.persist_library():
            raise OSError('歌单保存失败')
        panel.render_library()

    def finish(self):
        self.running = False
        self.cookie = ''
        self.close_dialog()
        text = f'下载完成：已保存 {self.saved} 首，跳过 {self.skipped} 首，失败 {self.failed} 首。'
        if self.saved:
            text += '\n已加入本地“B站下载”歌单。保存位置：' + str(self.directory)
        if self.results:
            text += '\n' + '\n'.join(self.results[:3])
        self.player.note.setText(text)

    def close_dialog(self):
        if self.dialog is not None:
            self.dialog.hide()
            self.dialog.deleteLater()
            self.dialog = None

    def cancel(self):
        self.running = False
        self.cookie = ''
        self.cancel_account()
        self.parts.cancel()
        if self.job is not None:
            self.job.stopped.set()
        self.close_dialog()
        self.player.note.setText('下载已取消，已保存的文件保留；正在清理本次未完成的临时文件。')
