"""Explicit user-selected downloads; account APIs and file transfer stay separate."""
from pathlib import Path
import sqlite3

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QProgressDialog

from netease_music.client import Client
from netease_music.downloads import Downloader, export_lrc
from netease_music.service import ApiError, SessionExpired
from netease_music.playback import clean_tracks
from netease_music.links import music_id


class NeteaseDownloads(QObject):
    def __init__(self, companion, cloud):
        super().__init__(companion)
        self.companion, self.cloud = companion, cloud
        self.client, self.transfer = Client(self), Downloader(self)
        self.client.completed.connect(self._prepared)
        self.client.failed.connect(self._failed)
        self.transfer.completed.connect(self._saved)
        self.transfer.failed.connect(lambda message: self._failed('transfer', message, False))
        self.transfer.warning.connect(self._warning)
        self.transfer.progress.connect(self._progress)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._next)
        self.dialog = None
        self.running = False
        self.items, self.results = [], []
        self.index = -1
        self.lyrics_only = False
        self.directory = None
        self.note = ''
        self.epoch = 0
        self.fetching_playlist = False
        self.playlist_title = self.playlist_note = self.local_playlist_id = ''
        self.saved_count = self.bound_count = self.failed_count = 0
        cloud.sessionChanged.connect(self.cancel)

    def start_playlist(self, playlist_id, directory=None):
        try:
            playlist_id = 'likes' if playlist_id == 'likes' else music_id(playlist_id)
        except ValueError:
            self.cloud.set_playback_status('歌单编号无效，请重新打开歌单。')
            return
        self.start([], False, directory, playlist_id=playlist_id)

    def start(self, tracks, lyrics_only=False, directory=None, *, playlist_id=None):
        epoch = self.epoch
        try:
            items = clean_tracks(tracks)
        except (TypeError, ValueError, AttributeError):
            self.cloud.set_playback_status('下载列表无效，请重新选择歌曲。')
            return
        if playlist_id is None and (not items or len(items) > 100):
            self.cloud.set_playback_status('每次请选择 1～100 首歌曲下载。')
            return
        if directory is None:
            default = self.companion.pet.panel.settings.value('netease_download_directory', '')
            default = default or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
            directory = QFileDialog.getExistingDirectory(self.cloud, '选择歌曲和 LRC 保存文件夹', str(default))
        if not directory:
            return
        if epoch != self.epoch:
            return
        destination = Path(directory)
        if not destination.is_dir():
            self.cloud.set_playback_status('保存文件夹不存在，请重新选择。')
            return
        self.cancel()
        self.directory, self.items, self.results = destination, items, []
        self.lyrics_only, self.running, self.index = bool(lyrics_only), True, -1
        self.fetching_playlist = playlist_id is not None
        self.playlist_title = self.playlist_note = self.local_playlist_id = ''
        self.saved_count = self.bound_count = self.failed_count = 0
        self.companion.pet.panel.settings.setValue('netease_download_directory', str(destination))
        self.dialog = QProgressDialog('', '取消下载', 0, len(items), self.cloud.window())
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        self.dialog.setLabel(label)
        self.dialog.setWindowTitle('保存 LRC' if lyrics_only else '下载音频与 LRC')
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setMinimumDuration(0)
        self.dialog.canceled.connect(self.cancel)
        self.dialog.setValue(0)
        self.dialog.show()
        if self.fetching_playlist:
            self.dialog.setWindowTitle('下载整个歌单＋LRC')
            self.dialog.setLabelText('正在读取完整歌单，包含尚未显示的曲目…')
            service = self.cloud._service()
            self.client.run('playlist_download', service.likes() if playlist_id == 'likes' else service.playlist(playlist_id))
        else:
            self._next()

    def _next(self):
        if not self.running:
            return
        self.index += 1
        if self.index >= len(self.items):
            self._finish()
            return
        self.note = ''
        self.dialog.setLabelText(f'{self.index + 1}/{len(self.items)} · {self.items[self.index]["title"]}\n正在读取下载权限与歌词…')
        self.client.run('prepare', self._prepare(self.cloud._service(), self.items[self.index], self.lyrics_only))

    @staticmethod
    def _prepare(service, item, lyrics_only):
        media = None
        if not lyrics_only:
            media = yield from service.media(item['id'], download=True)
            if media.get('unavailable') or media.get('trial') or not media.get('url'):
                return dict(media=media, lrc='', item=item, lyric_status='')
        try:
            song = yield from service.song(item['id'])
            return dict(media=media, lrc=song.get('lrc', ''), item=item,
                        lyric_status=song.get('lrc_status', '未返回逐句歌词'))
        except SessionExpired:
            raise
        except ApiError:
            return dict(media=media, lrc='', item=item, lyric_status='歌词获取失败，可稍后单独保存LRC')

    def _prepared(self, kind, result):
        if not self.running:
            return
        if kind == 'playlist_download':
            if not self.fetching_playlist:
                return
            try:
                self.items = clean_tracks(result['tracks'])
                if not self.items or len(result['tracks']) > 20000:
                    raise ValueError('歌单没有可读取的歌曲，或超过 20000 首。')
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                self._failed(kind, str(error), False)
                return
            self.fetching_playlist = False
            self.playlist_title = str(result.get('title') or '网易云歌单')[:1000]
            if not result.get('complete'):
                self.playlist_note = f'歌单读取不完整：本次只能处理已取得的 {len(self.items)}/{result.get("total", "未知")} 首。'
            self.dialog.setRange(0, len(self.items))
            self._next()
            return
        if self.fetching_playlist:
            return
        item = self.items[self.index]
        if result['item']['id'] != item['id']:
            return
        stem = item['title'] + (' - ' + item['artists'] if item['artists'] else '') + ' [' + item['id'] + ']'
        lyric = result.get('lrc', '')
        self.note = '' if lyric else result.get('lyric_status', '无逐句歌词')
        try:
            if self.lyrics_only:
                if not lyric:
                    self._failed(kind, self.note, False)
                    return
                path = export_lrc(self.directory, stem, lyric)
                self.saved_count += 1
                self._record('已保存 ' + Path(path).name)
                return
            media = result['media']
            if media.get('unavailable') or media.get('trial') or not media.get('url'):
                self._failed(kind, media.get('reason') or '没有完整下载权限；可尝试播放或仅保存LRC。', False)
                return
            self.transfer.start(media['url'], self.directory, stem, media['extension'], lyric,
                                expected_size=media.get('size', 0))
        except (ValueError, OSError) as error:
            self._failed(kind, str(error), False)

    def _progress(self, received, total):
        if self.running and self.dialog:
            progress = f'{received * 100 // total}%' if total > 0 else f'{received / 1048576:.1f} MiB'
            self.dialog.setLabelText(f'{self.index + 1}/{len(self.items)} · {self.items[self.index]["title"]}\n下载中：{progress}')

    def _warning(self, message):
        self.note = message

    def _saved(self, audio_path, lrc_path):
        if self.running:
            self.saved_count += 1
            detail = '已保存音频' + ('＋LRC' if lrc_path else '；' + (self.note or '无逐句歌词'))
            if lrc_path:
                try:
                    source = 'local:' + str(Path(audio_path).resolve())
                    self.companion.lyrics.import_file(lrc_path, source)
                    self.bound_count += 1
                    detail += '，歌词已自动绑定'
                except (ValueError, OSError, sqlite3.Error):
                    detail += '；歌词文件已保存，但自动绑定失败，可在歌词页重新导入'
            if self.playlist_title and Path(audio_path).suffix.lower() == '.mp3':
                try:
                    self._add_local_song(audio_path)
                    detail += '，已加入本地歌单'
                except (ValueError, OSError):
                    detail += '；加入本地歌单失败，文件仍保留'
            self._record(detail + '：' + Path(audio_path).name)

    def _add_local_song(self, audio_path):
        panel = self.companion.pet.panel
        library = panel.library
        playlist = next((item for item in library.playlists if item['id'] == self.local_playlist_id), None)
        if playlist is None:
            active = library.active_id
            self.local_playlist_id = library.create(self.playlist_title[:32] + '（下载）')
            playlist = library.active
            library.active_id = active
        path = str(Path(audio_path).resolve())
        if path not in playlist['paths']:
            playlist['paths'].append(path)
        # Persist without resetting the user's currently playing queue.
        panel.settings.setValue('library_v1', library.dumps())
        panel.settings.sync()
        panel.render_library()

    def _failed(self, kind, message, expired):
        if not self.running:
            return
        if expired:
            self.cancel()
            self.cloud._failed(kind, message, True)
            return
        if self.fetching_playlist:
            self.cancel()
            self.cloud.set_playback_status('歌单读取失败，未开始下载：' + message)
            return
        self.failed_count += 1
        self._record('未保存：' + message)

    def _record(self, message):
        if not self.running:
            return
        self.results.append(self.items[self.index]['title'] + ' · ' + message)
        self.dialog.setValue(self.index + 1)
        self.timer.start(150)

    def _finish(self):
        self.running = False
        dialog, self.dialog = self.dialog, None
        if dialog:
            dialog.close()
            dialog.deleteLater()
        summary = f'已保存 {self.saved_count} 首，歌词绑定 {self.bound_count} 首，失败 {self.failed_count} 首。'
        self.cloud.set_playback_status(summary + self.playlist_note + f' 保存位置：{self.directory}')
        box = QMessageBox(self.cloud.window())
        box.setWindowTitle('保存结果')
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(summary + '\n' + self.playlist_note + '\n保存位置：' + str(self.directory)
                    + ('\n已下载的 MP3 已加入本地“' + self.playlist_title[:32] + '（下载）”歌单。'
                       if self.local_playlist_id else ''))
        box.setDetailedText('\n'.join(self.results))
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()
        self.result_box = box

    def cancel(self):
        self.epoch += 1
        running, self.running = self.running, False
        self.fetching_playlist = False
        self.timer.stop()
        self.client.cancel()
        self.transfer.cancel()
        dialog, self.dialog = self.dialog, None
        if dialog:
            dialog.close()
            dialog.deleteLater()
        if running:
            self.cloud.set_playback_status('下载已取消；已经完成的文件保留。')
