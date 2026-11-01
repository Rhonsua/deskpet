"""Ordinary Kugou music browsing; audio remains owned by the host player."""
from pathlib import Path
import re
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .client import Client
from .service import Service
from .storage import Cache


def label(text):
    value = QLabel(str(text))
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setWordWrap(True)
    return value


def login_pixmap(result):
    """Encode the adapter's login URL locally without fetching external images."""
    import qrcode
    url = result['url']
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ValueError('二维码内容无效')
    qr = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    cells = qr.get_matrix()
    scale = max(1, 224 // len(cells))
    image = QImage(len(cells) * scale, len(cells) * scale, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    for y, row in enumerate(cells):
        for x, dark in enumerate(row):
            if dark:
                painter.fillRect(x * scale, y * scale, scale, scale, Qt.GlobalColor.black)
    painter.end()
    return QPixmap.fromImage(image)


class KugouWidget(QWidget):
    lyricsReady = Signal(str, str, str)
    bindRequested = Signal(str, str)
    playBoundRequested = Signal(str)
    playRequested = Signal(object, int)
    downloadRequested = Signal(object, bool)
    playlistDownloadRequested = Signal(str)
    sessionChanged = Signal()
    transportRequested = Signal(str)
    modeRequested = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.cache = Cache(Path(data_dir))
        self.session, warning = self.cache.load_session()
        self._closed = False
        self._busy = False
        self._request_generation = 0
        self._active_request = None
        self._job_private = False
        self._session_epoch = 0
        self._current_song = None
        self._current_playlist = None
        self._qr_key = ''
        self._qr_deadline = 0
        self._restore_on_show = bool(self.session)
        self._session_warning = ''
        self.client = Client(self)
        self.client.completed.connect(self._client_completed)
        self.client.failed.connect(self._client_failed)
        self.qr_timer = QTimer(self)
        self.qr_timer.setSingleShot(True)
        self.qr_timer.timeout.connect(self._poll_qr)
        self.setStyleSheet('QWidget{background:white;color:black;} QLineEdit,QPlainTextEdit,QTreeWidget,QListWidget{border:1px solid #AFC8D3;padding:5px;selection-background-color:#DCECF2;selection-color:black;} QPushButton{padding:5px 8px;}')
        outer = QVBoxLayout(self)
        outer.addWidget(label('搜索酷狗歌曲，或粘贴歌单分享链接；登录后可读取我的歌单。'))
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText('搜索歌名、歌手，或粘贴酷狗歌单分享链接')
        self.link.returnPressed.connect(self.fetch_link)
        row.addWidget(self.link, 1)
        self.fetch_button = QPushButton('搜索／打开歌单')
        self.fetch_button.clicked.connect(self.fetch_link)
        row.addWidget(self.fetch_button)
        layout.addLayout(row)
        self.songs = QTreeWidget()
        self.songs.setHeaderLabels(['歌曲', '歌手', '状态'])
        self.songs.setRootIsDecorated(False)
        self.songs.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.songs.currentItemChanged.connect(self._selected)
        self.songs.itemDoubleClicked.connect(lambda *_: self.play_song())
        layout.addWidget(self.songs, 1)
        row = QHBoxLayout()
        self.song_buttons = {}
        for text, action in [('播放歌曲', self.play_song), ('播放歌单', self.play_playlist),
                             ('下载歌曲＋LRC', lambda: self.download_songs(False)),
                             ('只保存LRC', lambda: self.download_songs(True))]:
            button = QPushButton(text)
            button.clicked.connect(action)
            self.song_buttons[text] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.download_playlist_button = QPushButton('一键下载整个歌单＋LRC…')
        self.download_playlist_button.clicked.connect(self.download_playlist)
        layout.addWidget(self.download_playlist_button)
        layout.addWidget(label('Ctrl / Shift 可多选歌曲，播放或保存所选歌曲。'))
        toggle = QPushButton('歌词预览 / 本地与B站绑定')
        toggle.setCheckable(True)
        layout.addWidget(toggle)
        tools = QWidget()
        tools.hide()
        toggle.toggled.connect(tools.setVisible)
        tool_layout = QVBoxLayout(tools)
        row = QHBoxLayout()
        for text, action in [('获取选中歌词', self.fetch_selected), ('绑定当前音源', self.bind_selected),
                             ('播放已绑定音源', self.play_bound)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        tool_layout.addLayout(row)
        self.lyric_view = QPlainTextEdit()
        self.lyric_view.setReadOnly(True)
        self.lyric_view.setMaximumHeight(130)
        tool_layout.addWidget(self.lyric_view)
        layout.addWidget(tools)
        self.tabs.addTab(page, '歌曲与歌单')
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('歌单只读快照；刷新失败保留上次结果，不修改本地音乐库。'))
        self.snapshot_list = QListWidget()
        self.snapshot_list.itemDoubleClicked.connect(self.open_snapshot)
        layout.addWidget(self.snapshot_list)
        button = QPushButton('查看选中快照')
        button.clicked.connect(self.open_snapshot)
        layout.addWidget(button)
        self.tabs.addTab(page, '云歌单快照')
        page = QWidget()
        layout = QVBoxLayout(page)
        self.account_status = label('')
        layout.addWidget(self.account_status)
        row = QHBoxLayout()
        self.account_buttons = {}
        for text, action in [('扫码登录酷狗', self.begin_qr), ('刷新歌单', self.fetch_collections), ('退出登录', self.logout)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            self.account_buttons[text] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.remember = QCheckBox('记住登录，下次打开直接显示歌单（本机加密保存）')
        self.remember.setChecked(True)
        self.remember.toggled.connect(self._remember_changed)
        layout.addWidget(self.remember)
        layout.addWidget(label('使用普通酷狗音乐 App 扫码，在手机确认登录。二维码过期可重新生成。'))
        self.qr_image = label('')
        self.qr_image.setFixedSize(240, 240)
        self.qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_image.hide()
        layout.addWidget(self.qr_image, 0, Qt.AlignmentFlag.AlignHCenter)
        self.collections = QTreeWidget()
        self.collections.setHeaderLabels(['类别', '歌单'])
        self.collections.setRootIsDecorated(False)
        self.collections.itemDoubleClicked.connect(self.open_collection)
        layout.addWidget(self.collections, 1)
        row = QHBoxLayout()
        for text, action in [('打开选中歌单', self.open_collection), ('下载选中歌单到本地…', self.download_collection)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs.addTab(page, '我的歌单')
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label('直接连接酷狗音乐服务，无需部署接口或填写 Cookie。音源与下载按当前账号权限提供。'))
        layout.addStretch()
        self.tabs.addTab(page, '连接说明')
        row = QHBoxLayout()
        self.transport_buttons = {}
        for text, action in [('上一首', 'previous'), ('播放 / 暂停', 'toggle'), ('下一首', 'next')]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, action=action: self.transportRequested.emit(action))
            self.transport_buttons[action] = button
            row.addWidget(button)
        self.play_mode = QComboBox()
        for text, mode in [('顺序播放', 'order'), ('列表循环', 'loop'), ('单曲循环', 'single'), ('随机播放', 'shuffle')]:
            self.play_mode.addItem(text, mode)
        self.play_mode.currentIndexChanged.connect(lambda index: self.modeRequested.emit(self.play_mode.itemData(index)))
        row.addWidget(self.play_mode)
        outer.addLayout(row)
        row = QHBoxLayout()
        self.status = label(warning or '可搜索歌曲、打开公开歌单，或扫码读取我的歌单。')
        row.addWidget(self.status, 1)
        self.cancel_button = QPushButton('取消当前请求／扫码')
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        outer.addLayout(row)
        self._account_label()
        self._refresh_snapshots()
        self.tabs.setCurrentIndex(2 if self.session else 0)

    def _service(self):
        return Service(session=self.session, progress=self.status.setText, cache=self.cache)

    def set_playback_status(self, text):
        self.status.setText(str(text)[:2000])

    @staticmethod
    def _track(item):
        raw = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(raw, dict):
            return None
        item_id = str(raw.get('id', '')).upper()
        if not re.fullmatch(r'[A-F0-9]{32}', item_id) or not isinstance(raw.get('title'), str):
            return None
        return dict(id=item_id, title=raw['title'][:1000], artists=str(raw.get('artists', ''))[:1000],
                    duration=raw.get('duration', 0) if type(raw.get('duration', 0)) is int else 0,
                    album_id=str(raw.get('album_id', ''))[:120],
                    album_audio_id=str(raw.get('album_audio_id', ''))[:120],
                    pay_type=raw.get('pay_type') if type(raw.get('pay_type')) is int else None,
                    unavailable=bool(raw.get('unavailable', False)))

    def selected_song(self):
        return self._track(self.songs.currentItem())

    def _selected_tracks(self):
        items = sorted(self.songs.selectedItems(), key=self.songs.indexOfTopLevelItem)
        if not items and self.songs.currentItem():
            items = [self.songs.currentItem()]
        return [track for item in items if (track := self._track(item))]

    def play_song(self):
        tracks = self._selected_tracks()
        if tracks:
            self.playRequested.emit(tracks, 0)
        else:
            self.status.setText('请先选择歌曲。')

    def play_playlist(self):
        tracks = []
        start = 0
        for index in range(self.songs.topLevelItemCount()):
            item = self.songs.topLevelItem(index)
            track = self._track(item)
            if track:
                if item is self.songs.currentItem():
                    start = len(tracks)
                tracks.append(track)
        if tracks:
            self.playRequested.emit(tracks, start)
        else:
            self.status.setText('请先搜索歌曲或打开歌单。')

    def download_songs(self, lyrics_only=False):
        tracks = self._selected_tracks()
        if not tracks:
            self.status.setText('请先选择歌曲。')
        elif len(tracks) > 100:
            self.status.setText('单次最多保存100首，请缩小选择范围。')
        else:
            self.downloadRequested.emit(tracks, bool(lyrics_only))

    def download_playlist(self):
        if self._current_playlist:
            self.playlistDownloadRequested.emit(str(self._current_playlist['id']))
        else:
            self.status.setText('请先打开需要下载的歌单。')

    def download_collection(self):
        item = self.collections.currentItem()
        if item and self.session:
            self.playlistDownloadRequested.emit(str(item.data(0, Qt.ItemDataRole.UserRole)))
        else:
            self.status.setText('请登录并选择歌单。')

    def _run(self, kind, operation):
        if self._closed:
            operation.close()
            return
        self.qr_timer.stop()
        if kind not in ('qr', 'qr_check'):
            self._qr_key = ''
            self.qr_image.clear()
            self.qr_image.hide()
            self.collections.show()
        self._busy = True
        self._job_private = bool(self.session)
        self.status.setText('正在读取，可取消当前请求。')
        self._request_generation += 1
        self._active_request = f'{kind}:{self._request_generation}'
        self.client.run(self._active_request, operation)

    def _client_completed(self, token, result):
        if self._closed or not self._busy or token != self._active_request:
            return
        self._active_request = None
        self._completed(token.rsplit(':', 1)[0], result)

    def _client_failed(self, token, message, expired):
        if self._closed or not self._busy or token != self._active_request:
            return
        self._active_request = None
        self._failed(token.rsplit(':', 1)[0], message, expired)

    def fetch_link(self):
        text = self.link.text().strip()
        if not text:
            self.status.setText('请输入歌名、歌手或歌单分享链接。')
            return
        if re.fullmatch(r'[A-Fa-f0-9]{32}', text):
            self._run('song', self._service().song(text.upper()))
        elif '://' in text:
            self._run('playlist', self._service().resolve_playlist(text))
        elif text.startswith(('collection_', 'user_')):
            self._run('playlist', self._service().playlist(text))
        else:
            self._run('search', self._service().search(text))

    def fetch_selected(self):
        track = self.selected_song()
        if track:
            self._run('song_selected', self._service().song(track))
        else:
            self.status.setText('请先选择歌曲。')

    def _selected(self, *_):
        self._current_song = None
        self.lyric_view.clear()

    def bind_selected(self):
        track = self.selected_song()
        if track and self._current_song and track['id'] == self._current_song.get('id') and self._current_song.get('lrc'):
            self.lyricsReady.emit(track['id'], track['title'], self._current_song['lrc'])
        else:
            self.status.setText('请先获取选中歌曲的可用歌词。')

    def play_bound(self):
        track = self.selected_song()
        if track:
            self.playBoundRequested.emit(track['id'])

    def _fill_songs(self, tracks):
        self.songs.clear()
        for track in tracks:
            item = QTreeWidgetItem([str(track.get('title', '')), str(track.get('artists', '')), '暂不可用' if track.get('unavailable') else ''])
            item.setData(0, Qt.ItemDataRole.UserRole, track)
            self.songs.addTopLevelItem(item)
        if self.songs.topLevelItemCount():
            self.songs.setCurrentItem(self.songs.topLevelItem(0))

    def _show_playlist(self, data, cached_at=''):
        self._current_playlist = data
        self._fill_songs(data['tracks'])
        self.tabs.setCurrentIndex(0)
        self.status.setText(f'{data.get("title", "歌单")}：{len(data["tracks"])}/{data.get("total", len(data["tracks"]))}首，'
                            + ('完整。' if data.get('complete') else '部分结果。')
                            + '；'.join(data.get('warnings', [])) + (f' 快照时间：{cached_at}' if cached_at else ''))

    def _refresh_snapshots(self):
        self.snapshot_list.clear()
        try:
            for raw in self.cache.snapshots(False) + (self.cache.snapshots(True) if self.session else []):
                data = raw['data']
                item = QListWidgetItem(f'{data.get("title", raw["id"])} · {len(data.get("tracks", []))}/{data.get("total", 0)} · {raw["fetched_at"]}')
                item.setData(Qt.ItemDataRole.UserRole, raw)
                self.snapshot_list.addItem(item)
        except (OSError, ValueError, TypeError, KeyError):
            self.status.setText('部分快照无法读取，请重新打开原歌单。')

    def open_snapshot(self, *_):
        item = self.snapshot_list.currentItem()
        if item:
            self.cancel()
            raw = item.data(Qt.ItemDataRole.UserRole)
            self._show_playlist(raw['data'], raw['fetched_at'])

    def begin_qr(self):
        if not self._logout(False):
            self.status.setText('旧账号缓存清理失败，请检查目录权限后重试。')
            return
        self.tabs.setCurrentIndex(2)
        self._run('qr', self._service().qr_create())

    def _poll_qr(self):
        if self._closed or not self._qr_key:
            return
        if time.monotonic() >= self._qr_deadline:
            self.cancel()
            self.status.setText('二维码已过期，请重新扫码。')
            return
        self._run('qr_check', self._service().qr_check(self._qr_key))

    def fetch_collections(self):
        if self.session:
            self._run('collections', self._service().collections())
        else:
            self.status.setText('请先使用普通酷狗音乐 App 扫码登录。')

    def open_collection(self, *_):
        item = self.collections.currentItem()
        if item and self.session:
            self._run('playlist', self._service().playlist(item.data(0, Qt.ItemDataRole.UserRole)))

    def _account_label(self):
        name = str(self.session.get('nickname') or self.session.get('userid', '')) if self.session else ''
        self.account_status.setText('已登录：' + name if self.session else '登录酷狗，查看创建和收藏的歌单')
        self.account_buttons['扫码登录酷狗'].setText('重新扫码登录' if self.session else '扫码登录酷狗')
        for name in ('刷新歌单', '退出登录'):
            self.account_buttons[name].setEnabled(bool(self.session))

    def _remember_changed(self, checked):
        try:
            if checked and self.session:
                self.cache.save_session(self.session)
            elif not checked:
                self.cache.path('session.json').unlink(missing_ok=True)
        except (OSError, ValueError):
            self.status.setText('本机登录保存设置更新失败，请检查数据目录权限。')

    def _accept_session(self, session):
        self.cancel()
        self.session = session
        self._session_epoch += 1
        self.sessionChanged.emit()
        self._account_label()
        self._session_warning = ''
        if self.remember.isChecked():
            try:
                self.cache.save_session(session)
            except (OSError, ValueError):
                self._session_warning = ' 本次登录有效，但无法加密保存；下次需重新扫码。'
        self.fetch_collections()

    def _logout(self, show=True):
        self.cancel()
        self._restore_on_show = False
        self.session = None
        self._session_epoch += 1
        self.sessionChanged.emit()
        self._current_song = self._current_playlist = None
        self.songs.clear()
        self.lyric_view.clear()
        self.collections.clear()
        self._account_label()
        success = True
        try:
            self.cache.clear_private()
        except (OSError, ValueError):
            success = False
        self._refresh_snapshots()
        if show:
            self.status.setText('已退出并清理本机登录与个人缓存。' if success else '已退出，部分本机登录或缓存未能清理，请检查目录权限。')
        return success

    def logout(self):
        self._logout()

    def _completed(self, kind, result):
        if self._closed:
            return
        self._busy = False
        try:
            if kind == 'search':
                self._current_playlist = None
                self._fill_songs(result['tracks'])
                self.tabs.setCurrentIndex(0)
                self.status.setText(f'显示 {len(result["tracks"])} 首，共 {result.get("total", len(result["tracks"]))} 条结果。'
                                    + (' 部分结果，请缩小关键词范围。' if not result.get('complete', True) else ''))
            elif kind in ('song', 'song_selected'):
                if kind == 'song':
                    self._current_playlist = None
                    self._fill_songs([result])
                    self.tabs.setCurrentIndex(0)
                track = self.selected_song()
                if track and track['id'] == result['id']:
                    self._current_song = result
                    self.lyric_view.setPlainText(result.get('lrc', ''))
                    self.status.setText(result.get('lrc_status', '歌词已读取。'))
                self.cache.save_snapshot('song', result['id'], result, self._job_private)
            elif kind == 'playlist':
                self._show_playlist(result)
                saved = self.cache.save_snapshot('playlist', result['id'], result, self._job_private)
                self._refresh_snapshots()
                if saved is False:
                    self.status.setText(self.status.text() + ' 上次完整快照已保留。')
            elif kind == 'collections':
                self.collections.clear()
                for entry in result['playlists']:
                    item = QTreeWidgetItem([str(entry.get('category', '歌单')), str(entry['title'])])
                    item.setData(0, Qt.ItemDataRole.UserRole, entry['id'])
                    self.collections.addTopLevelItem(item)
                self.tabs.setCurrentIndex(2)
                self.status.setText(f'已读取 {self.collections.topLevelItemCount()} 个歌单。'
                                    + (' 部分结果，可稍后刷新。' if not result.get('complete', True) else '')
                                    + self._session_warning)
            elif kind == 'qr':
                self.qr_image.setPixmap(login_pixmap(result))
                self.collections.hide()
                self.qr_image.show()
                self._qr_key = result['key']
                self._qr_deadline = time.monotonic() + 180
                self.status.setText('请用普通酷狗音乐 App 扫码，并在手机确认登录。')
                self.qr_timer.start(3000)
            elif kind == 'qr_check':
                status = result['status']
                if status == 'confirmed':
                    self._accept_session(result['session'])
                elif status in ('waiting', 'scanned'):
                    self.status.setText('等待扫码。' if status == 'waiting' else '已扫码，请在手机酷狗音乐 App 中确认。')
                    self.qr_timer.start(3000)
                else:
                    self.cancel()
                    self.status.setText('二维码已过期，请重新扫码。' if status == 'expired' else '登录已取消，请重新扫码。')
        except (ImportError, OSError, ValueError, TypeError, KeyError):
            self.qr_timer.stop()
            self._qr_key = ''
            self.status.setText('返回内容显示或本机保存失败，请重试；尚未确认缓存或凭据保存成功。')

    def _failed(self, kind, message, expired):
        if self._closed:
            return
        self.cancel()
        if expired:
            self._logout(False)
        self.status.setText(str(message)[:1600] + (' 请重新扫码登录。' if expired else ' 可重试，上次快照已保留。'))

    def cancel(self):
        self._request_generation += 1
        self._active_request = None
        self.qr_timer.stop()
        self._qr_key = ''
        self.qr_image.clear()
        self.qr_image.hide()
        self.collections.show()
        self.client.cancel()
        self._busy = False

    def shutdown(self):
        if not self._closed:
            self._closed = True
            self.cancel()

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._restore_on_show and self.session and not self._closed:
            self._restore_on_show = False
            self.fetch_collections()
