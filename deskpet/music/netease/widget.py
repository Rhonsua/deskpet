"""On-demand white/black NetEase browser. No playback or reward accounting."""
import base64
from pathlib import Path
import time
from urllib.parse import urlencode

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QMessageBox, QComboBox)

from .client import Client
from .links import api_base, canonical_link, parse_link, music_id
from .service import ApiError, Service
from .storage import Cache


def label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def login_pixmap(result):
    """Generate direct-login QR pixels locally; never load a remote QR image."""
    if 'url' in result:
        key = result.get('key')
        if not isinstance(key, str) or not key or len(key) > 512:
            raise ApiError('二维码内容不兼容，请重新生成。')
        expected = 'https://music.163.com/login?' + urlencode({'codekey': key})
        if result['url'] != expected:
            raise ApiError('二维码不是预期的网易云登录地址。')
        import qrcode
        matrix = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
        matrix.add_data(expected)
        matrix.make(fit=True)
        cells = matrix.get_matrix()
        # Integer module size preserves sharp scanner-readable edges.
        scale = max(2, 240 // len(cells))
        image = QImage(len(cells) * scale, len(cells) * scale, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        for y, row in enumerate(cells):
            for x, dark in enumerate(row):
                if dark:
                    painter.fillRect(x * scale, y * scale, scale, scale, Qt.GlobalColor.black)
        painter.end()
        return QPixmap.fromImage(image)
    image = result['image']
    if not image.startswith('data:image/png;base64,') or len(image) > 700000:
        raise ApiError('扫码图像格式不兼容。')
    content = base64.b64decode(image.split(',', 1)[1], validate=True)
    buffer = QBuffer()
    buffer.setData(QByteArray(content))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer, b'png')
    size = reader.size()
    if not 0 < size.width() <= 1024 or not 0 < size.height() <= 1024:
        raise ApiError('扫码图像大小不兼容。')
    pixmap = QPixmap.fromImage(reader.read())
    if pixmap.isNull():
        raise ApiError('无法显示扫码图像。')
    return pixmap.scaled(240, 240, Qt.AspectRatioMode.KeepAspectRatio)


class NeteaseWidget(QWidget):
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
        self.base, warning = self.cache.settings()
        self.session, session_warning = self.cache.load_session(self.base)
        self._closed = False
        self._session_epoch = 0
        self.sessionChanged.connect(self._session_changed)
        self._busy = False
        self._qr_key = ''
        self._qr_attempts = 0
        self._qr_deadline = 0
        self._current_song = None
        self._current_playlist = None
        self._job_private = False
        self._restore_on_show = bool(self.session)
        self._session_warning = ''
        self.browser_login = None
        self._browser_pending = False
        self._browser_epoch = 0
        self._session_recheck = None
        self.client = Client(self)
        self.client.completed.connect(self._completed)
        self.client.failed.connect(self._failed)
        self.qr_timer = QTimer(self)
        self.qr_timer.setSingleShot(True)
        self.qr_timer.timeout.connect(self._poll_qr)
        self.setStyleSheet('QWidget{background:white;color:black;} QLineEdit,QPlainTextEdit,QTreeWidget,QListWidget{border:1px solid #AFC8D3;padding:5px;selection-background-color:#DCECF2;selection-color:black;} QPushButton{padding:5px 8px;}')
        outer = QVBoxLayout(self)
        outer.addWidget(label('登录后打开我的歌单，点播放即可听歌，歌词自动同步。'))
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText('https://music.163.com/song?id=… 或 playlist?id=…')
        row.addWidget(self.link, 1)
        self.fetch_button = QPushButton('联网获取／刷新')
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
        self.song_buttons = {}
        primary = QHBoxLayout()
        for text, action in [('播放歌曲', self.play_song), ('播放歌单', self.play_playlist),
                             ('下载歌曲＋LRC', lambda: self.download_songs(False)),
                             ('只保存LRC', lambda: self.download_songs(True))]:
            button = QPushButton(text)
            button.clicked.connect(action)
            self.song_buttons[text] = button
            primary.addWidget(button)
        layout.addLayout(primary)
        self.download_playlist_button = QPushButton('一键下载整个歌单＋LRC…')
        self.download_playlist_button.clicked.connect(self.download_playlist)
        layout.addWidget(self.download_playlist_button)
        layout.addWidget(label('Ctrl / Shift 可多选歌曲，下载时选择保存文件夹。'))
        lyric_tools_toggle = QPushButton('歌词预览 / 本地与B站绑定')
        lyric_tools_toggle.setCheckable(True)
        layout.addWidget(lyric_tools_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        lyric_tools = QWidget()
        lyric_tools.setVisible(False)
        lyric_layout = QVBoxLayout(lyric_tools)
        lyric_layout.setContentsMargins(0, 0, 0, 0)
        lyric_tools_toggle.toggled.connect(lyric_tools.setVisible)
        actions = QHBoxLayout()
        for text, action in [('获取选中歌词', self.fetch_selected), ('绑定当前音源', self.bind_selected),
                             ('播放已绑定音源', self.play_bound), ('打开网易云原页', self.open_original)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            actions.addWidget(button)
        lyric_layout.addLayout(actions)
        lyric_layout.addWidget(label('为本地或B站音源绑定时，请核对原唱、Live及剪辑版本是否一致。'))
        self.lyric_view = QPlainTextEdit()
        self.lyric_view.setReadOnly(True)
        self.lyric_view.setPlaceholderText('选择歌曲后获取逐句LRC。无歌词或接口失败不影响现有播放。')
        self.lyric_view.setMaximumHeight(130)
        lyric_layout.addWidget(self.lyric_view)
        layout.addWidget(lyric_tools)
        self.tabs.addTab(page, '歌曲与歌单')
        snapshots = QWidget()
        snapshot_layout = QVBoxLayout(snapshots)
        snapshot_layout.addWidget(label('独立只读快照，不加入或修改本地音乐库。部分失败的快照会明确显示读取数量；刷新失败保留上次快照。'))
        self.snapshot_list = QListWidget()
        self.snapshot_list.itemDoubleClicked.connect(self.open_snapshot)
        snapshot_layout.addWidget(self.snapshot_list)
        button = QPushButton('查看选中快照')
        button.clicked.connect(self.open_snapshot)
        snapshot_layout.addWidget(button)
        self.tabs.addTab(snapshots, '云歌单快照')
        account = QWidget()
        account_layout = QVBoxLayout(account)
        self.account_status = label('')
        account_layout.addWidget(self.account_status)
        account_actions = QHBoxLayout()
        self.account_buttons = {}
        login_actions = QHBoxLayout()
        primary_login = QPushButton('官方网页登录（推荐）')
        primary_login.clicked.connect(self.begin_browser_login)
        self.account_buttons['扫码登录网易云'] = primary_login
        login_actions.addWidget(primary_login)
        self.direct_login_button = QPushButton('直接扫码（备用）')
        self.direct_login_button.clicked.connect(self.begin_qr)
        login_actions.addWidget(self.direct_login_button)
        account_layout.addLayout(login_actions)
        self.browser_status = label('')
        self.browser_status.hide()
        account_layout.addWidget(self.browser_status)
        self.browser_recheck = QPushButton('我已在网页完成登录，重新检测')
        self.browser_recheck.clicked.connect(self.recheck_browser_login)
        self.browser_recheck.hide()
        account_layout.addWidget(self.browser_recheck)
        for text, action in [('刷新歌单', self.fetch_collections),
                             ('我喜欢的音乐', self.fetch_likes), ('退出登录', self.logout)]:
            button = QPushButton(text)
            button.clicked.connect(action)
            self.account_buttons[text] = button
            account_actions.addWidget(button)
        account_layout.addLayout(account_actions)
        self.remember = QCheckBox('记住登录，下次打开直接显示歌单（本机加密保存）')
        self.remember.setChecked(True)
        self.remember.toggled.connect(self._remember_changed)
        account_layout.addWidget(self.remember)
        account_layout.addWidget(label('推荐在官方网页完成登录和验证，成功后自动返回歌单。\n直接扫码不可用时，请使用官方网页登录；无需安装电脑客户端。'))
        self.qr_image = QLabel()
        # QLabel's wrapped-text height-for-width can remain zero after clear()
        # then setPixmap(). Reserve a real square independent of text layout.
        self.qr_image.setFixedSize(240, 240)
        self.qr_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_image.hide()
        account_layout.addWidget(self.qr_image, 0, Qt.AlignmentFlag.AlignHCenter)
        self.collections = QTreeWidget()
        self.collections.setHeaderLabels(['类别', '歌单'])
        self.collections.setRootIsDecorated(False)
        self.collections.itemDoubleClicked.connect(self.open_collection)
        account_layout.addWidget(self.collections, 1)
        button = QPushButton('打开选中歌单')
        button.clicked.connect(self.open_collection)
        account_layout.addWidget(button)
        self.download_collection_button = QPushButton('下载选中歌单到本地…')
        self.download_collection_button.clicked.connect(self.download_collection)
        account_layout.addWidget(self.download_collection_button)
        self.tabs.addTab(account, '我的歌单')
        config = QWidget()
        config_layout = QVBoxLayout(config)
        config_layout.addWidget(label('默认直接连接网易云，扫码不需要填写地址。仅在需要自行指定兼容服务时配置下方选项；该服务会收到登录凭据，请确认可信。留空并保存可恢复默认连接。'))
        form = QFormLayout()
        self.api_input = QLineEdit(self.base)
        self.api_input.setPlaceholderText('https://可信域名 或 http://127.0.0.1:3000')
        form.addRow('社区API地址', self.api_input)
        config_layout.addLayout(form)
        self.trust = QCheckBox('我信任该服务接收我的网易云独立登录凭据')
        self.trust.setChecked(bool(self.base))
        config_layout.addWidget(self.trust)
        button = QPushButton('保存接口（更改地址会退出并清除个人缓存）')
        button.clicked.connect(self.save_api)
        config_layout.addWidget(button)
        config_layout.addStretch()
        self.tabs.addTab(config, '高级连接设置')
        self.tabs.setTabVisible(3, False)
        advanced = QPushButton('高级连接设置')
        advanced.setCheckable(True)
        advanced.toggled.connect(self.show_advanced)
        outer.addWidget(advanced, 0, Qt.AlignmentFlag.AlignRight)
        transport = QHBoxLayout()
        self.transport_buttons = {}
        for text, action in [('上一首', 'previous'), ('播放 / 暂停', 'toggle'), ('下一首', 'next')]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, action=action: self.transportRequested.emit(action))
            self.transport_buttons[action] = button
            transport.addWidget(button)
        self.play_mode = QComboBox()
        for text, mode in [('顺序播放', 'order'), ('列表循环', 'loop'), ('单曲循环', 'single'), ('随机播放', 'shuffle')]:
            self.play_mode.addItem(text, mode)
        self.play_mode.currentIndexChanged.connect(lambda index: self.modeRequested.emit(self.play_mode.itemData(index)))
        transport.addWidget(self.play_mode)
        outer.addLayout(transport)
        bottom = QHBoxLayout()
        self.status = label(warning or session_warning or '登录后自动读取我的歌单；也可在“歌曲与歌单”粘贴公开链接。')
        bottom.addWidget(self.status, 1)
        self.cancel_button = QPushButton('取消当前请求／扫码')
        self.cancel_button.clicked.connect(self.cancel)
        bottom.addWidget(self.cancel_button)
        outer.addLayout(bottom)
        self._account_label()
        self._refresh_snapshots()
        self.tabs.setCurrentIndex(2)

    def show_advanced(self, visible):
        self.tabs.setTabVisible(3, visible)
        self.tabs.setCurrentIndex(3 if visible else 2)

    def selected_song(self):
        item = self.songs.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return dict(id=data['id'], title=data['title']) if isinstance(data, dict) else None

    def _session_changed(self):
        self._session_epoch += 1
        self._session_recheck = None
        if getattr(self,'_browser_pending',False):
            self._browser_pending = False
            self.browser_recheck.hide()
            self.browser_status.hide()
            if self.browser_login is not None:self.browser_login.cancel()

    @staticmethod
    def _track(item):
        raw = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(raw, dict):
            return None
        try:
            item_id = music_id(raw.get('id'))
        except ValueError:
            return None
        title = raw.get('title')
        if not isinstance(title, str) or not title.strip():
            return None
        artists = raw.get('artists', '')
        duration = raw.get('duration', 0)
        # Only metadata crosses the playback/download boundary, never a cached URL or credential.
        return dict(id=item_id, title=title[:1000], artists=artists[:1000] if isinstance(artists, str) else '',
                    duration=duration if type(duration) is int and duration >= 0 else 0,
                    unavailable=bool(raw.get('unavailable', False)))

    def set_playback_status(self, text):
        self.status.setText(str(text)[:2000])

    def play_song(self):
        track = self._track(self.songs.currentItem())
        if track is None:
            self.status.setText('请先选择歌曲。')
            return
        self.status.setText('正在按账号权限获取音源；仅可试听时会明确标识。')
        self.playRequested.emit([track], 0)

    def play_playlist(self):
        tracks = []
        start = 0
        for index in range(self.songs.topLevelItemCount()):
            item = self.songs.topLevelItem(index)
            track = self._track(item)
            if track is not None:
                if item is self.songs.currentItem():
                    start = len(tracks)
                tracks.append(track)
        if not tracks:
            self.status.setText('请先打开一张歌单或读取歌曲。')
            return
        self.status.setText(f'准备播放已加载的 {len(tracks)} 首，从当前歌曲开始；不可播放或试听权限以音源返回为准。')
        self.playRequested.emit(tracks, start)

    def download_songs(self, lyrics_only=False):
        items = sorted(self.songs.selectedItems(), key=self.songs.indexOfTopLevelItem)
        if not items and self.songs.currentItem():
            items = [self.songs.currentItem()]
        tracks = [track for item in items if (track := self._track(item)) is not None]
        if not tracks:
            self.status.setText('请先选中需要保存的歌曲。')
            return
        if len(tracks) > 100:
            self.status.setText('单次最多保存 100 首，请缩小选择范围后重试。')
            return
        if len(tracks) > 20:
            epoch = self._session_epoch
            answer = QMessageBox.question(self, '确认批量保存',
                f'将为选中的 {len(tracks)} 首获取' + ('歌词？' if lyrics_only else '可用音频和歌词？'))
            if epoch != self._session_epoch:
                self.status.setText('账号或连接已变化，已取消旧选择；请重新选择需要保存的歌曲。')
                return
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.status.setText(f'准备保存选中的 {len(tracks)} 首；不可获取的音频或歌词会分别说明。')
        self.downloadRequested.emit(tracks, bool(lyrics_only))

    def download_playlist(self):
        if not self._current_playlist:
            self.status.setText('请先打开要下载的歌单。')
            return
        target = 'likes' if self._current_playlist.get('download_source') == 'likes' else music_id(self._current_playlist['id'])
        self.playlistDownloadRequested.emit(target)

    def download_collection(self):
        item = self.collections.currentItem()
        if item is None or not self.session:
            self.status.setText('请登录并选中要下载的歌单。')
            return
        self.playlistDownloadRequested.emit(music_id(item.data(0, Qt.ItemDataRole.UserRole)))

    def _selected(self, *_):
        self._current_song = None
        self.lyric_view.clear()

    def _service(self):
        return Service(self.base, self.session, self.status.setText)

    def _clear_qr(self):
        self.qr_image.clear()
        self.qr_image.hide()

    def _run(self, kind, operation):
        if kind != 'session_recheck':self._session_recheck = None
        if self._closed:
            operation.close()
            return
        self.qr_timer.stop()
        if kind not in ('qr', 'qr_check'):
            self._qr_key = ''
            self._clear_qr()
            self._browser_pending = False
            self.browser_recheck.hide()
            self.browser_status.hide()
            if self.browser_login is not None and self.browser_login.active:
                self.browser_login.cancel()
        self._job_private = bool(self.session)
        self._busy = True
        self.status.setText('正在后台读取，可取消；不会控制现有播放器。')
        self.client.run(kind, operation)

    def fetch_link(self):
        try:
            kind, item_id = parse_link(self.link.text())
            service = self._service()
            self._run(kind, service.song(item_id) if kind == 'song' else service.playlist(item_id))
        except (ValueError, OSError):
            self.status.setText('链接或接口设置无效，请使用完整的网易云歌曲／歌单链接。')

    def fetch_selected(self):
        song = self.selected_song()
        if not song:
            self.status.setText('请先选择一首云歌曲。')
            return
        cached = self.cache.snapshot('song', song['id'], bool(self.session), fresh=True)
        if cached and isinstance(cached.get('data'), dict) and cached['data'].get('lrc'):
            self.cancel()
            self._show_song(cached['data'], replace=False)
            self.status.setText('使用24小时内的歌词缓存；如需重新获取，请用歌曲链接联网刷新。')
            return
        self._run('song_selected', self._service().song(song['id']))

    def bind_selected(self):
        song = self.selected_song()
        if not song or not self._current_song or self._current_song['id'] != song['id'] or not self._current_song.get('lrc'):
            self.status.setText('请先获取选中歌曲的可用逐句歌词，再绑定当前音源。')
            return
        self.lyricsReady.emit(song['id'], song['title'], self._current_song['lrc'])

    def play_bound(self):
        song = self.selected_song()
        if song:
            self.playBoundRequested.emit(song['id'])
        else:
            self.status.setText('请先选择歌曲；未绑定时宿主不会播放网易云条目。')

    def open_original(self):
        song = self.selected_song()
        if song:
            QDesktopServices.openUrl(QUrl(canonical_link('song', song['id'])))
        elif self._current_playlist:
            QDesktopServices.openUrl(QUrl(canonical_link('playlist', self._current_playlist['id'])))

    def _fill_songs(self, songs):
        self.songs.clear()
        for song in songs:
            item = QTreeWidgetItem([song['title'], song.get('artists', ''), '信息不可读，播放待验证' if song.get('unavailable') else '信息可读，播放待验证'])
            item.setData(0, Qt.ItemDataRole.UserRole, song)
            self.songs.addTopLevelItem(item)
        if self.songs.topLevelItemCount():
            self.songs.setCurrentItem(self.songs.topLevelItem(0))

    def _show_song(self, song, replace=True):
        if replace:
            self._current_playlist = None
            self._fill_songs([song])
        selected = self.selected_song()
        if not selected or selected['id'] != song['id']:
            self.status.setText('歌词已读取，但当前选择已变化；未绑定任何音源。')
            return
        self._current_song = song
        self.lyric_view.setPlainText(song.get('lrc', ''))
        self.status.setText(song.get('lrc_status', '歌曲信息已读取。'))

    def _show_playlist(self, data, cached_at=''):
        self._current_playlist = data
        self._fill_songs(data['tracks'])
        notice = '；'.join(data.get('warnings', []))
        self.status.setText(f'{data["title"]}：{data["count"]}/{data["total"]}首，'
                            f'{"完整" if data.get("complete") else "部分结果"}。' + notice +
                            (f' 快照时间：{cached_at}' if cached_at else '') + ' 不改变本地歌单。')
        self.tabs.setCurrentIndex(0)

    def _refresh_snapshots(self):
        self.snapshot_list.clear()
        try:
            entries = self.cache.snapshots(False)
            if self.session:
                entries += self.cache.snapshots(True)
            for raw in entries:
                data = raw.get('data')
                if not isinstance(data, dict) or not isinstance(data.get('tracks'), list):
                    continue
                item = QListWidgetItem(f'{data.get("title", raw["id"])} · {data.get("count", 0)}/{data.get("total", 0)} · {raw["fetched_at"]}')
                item.setData(Qt.ItemDataRole.UserRole, raw)
                self.snapshot_list.addItem(item)
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText('部分云歌单快照无法读取，可重新获取。')

    def open_snapshot(self, *_):
        item = self.snapshot_list.currentItem()
        if item:
            self.cancel()
            raw = item.data(Qt.ItemDataRole.UserRole)
            try:
                data = dict(raw['data'])
                if raw.get('kind') == 'likes':
                    data['download_source'] = 'likes'
                self._show_playlist(data, raw['fetched_at'])
            except (KeyError, TypeError, ValueError):
                self.status.setText('快照格式损坏，请重新获取原歌单。')

    def begin_browser_login(self):
        if self.base:
            self.status.setText('官方网页登录使用默认直连。请先在高级连接设置清空自定义地址并保存。')
            return
        if not self._logout(False):
            self.status.setText('旧登录数据清理失败，暂未打开新登录窗口，请检查目录权限。')
            return
        if self.browser_login is None:
            from .browser_login import BrowserLogin
            self.browser_login = BrowserLogin(self)
            self.browser_login.completed.connect(self._browser_completed)
            self.browser_login.failed.connect(self._browser_failed)
            self.browser_login.status.connect(self._browser_status)
        self._browser_pending = True
        self._browser_epoch = self._session_epoch
        self.browser_recheck.show()
        self.browser_status.show()
        self._browser_status('正在打开网易云官方网页；请在网页完成扫码和手机确认。尚未收到账号登录结果。')
        self.browser_login.start()

    def _browser_current(self):
        return not self._closed and self._browser_pending and self._browser_epoch==self._session_epoch and not self.base

    def _browser_status(self,message):
        if self._browser_current() and isinstance(message,str):
            self.browser_status.setText(message[:600])
            self.browser_status.show()
            self.status.setText(message[:600])

    def recheck_browser_login(self):
        if not self._browser_current():return
        self._browser_status('已请求重新检测网页登录结果。若手机尚未确认，请先在手机完成确认；不需要复制登录凭据。')
        self.browser_login.request_check()

    def _browser_completed(self, session):
        if not self._browser_current():return
        self._browser_pending = False
        self.browser_recheck.hide()
        self.browser_status.hide()
        self._accept_session(session)

    def _browser_failed(self, message):
        if self._browser_current():
            self._browser_pending = False
            self.browser_recheck.hide()
            message += ' 可重新打开官方网页登录重试。'
            self.browser_status.setText(message)
            self.browser_status.show()
            self.status.setText(message)

    def begin_qr(self):
        if self.base and not self.trust.isChecked():
            self.status.setText('当前指定了自定义服务。请在高级连接设置确认信任，或清空地址并保存以恢复默认连接。')
            return
        # Always clear before accepting a different account, even if a previous
        # logout failed after dropping the in-memory session.
        if not self._logout(False):
            self.status.setText('旧个人缓存或凭据无法清理，已停止扫码，避免混入其他账号内容。请检查目录权限。')
            return
        self._qr_attempts = 0
        self.tabs.setCurrentIndex(2)
        self.qr_image.setText('正在生成二维码…')
        self.qr_image.show()
        self._run('qr', self._service().qr())

    def _poll_qr(self):
        if self._qr_key and not self._closed:
            self._qr_attempts += 1
            if self._qr_attempts > 60 or time.monotonic() >= self._qr_deadline:
                self.cancel()
                self.status.setText('二维码等待超过3分钟，请重新扫码。')
                return
            self._run('qr_check', self._service().check_qr(self._qr_key))

    def fetch_collections(self):
        if not self.session:
            self.status.setText('请先扫码登录；不读取其他程序的Cookie。')
            return
        self._run('collections', self._verified_collections())

    def _verified_collections(self):
        service = self._service()
        yield from service.verify_session()
        return (yield from service.collections())

    def fetch_likes(self):
        if not self.session:
            self.status.setText('请先扫码登录。')
            return
        self._run('likes', self._verified_likes())

    def _verified_likes(self):
        service = self._service()
        yield from service.verify_session()
        return (yield from service.likes())

    def open_collection(self, *_):
        item = self.collections.currentItem()
        if item and self.session:
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            self.link.setText(canonical_link('playlist', item_id))
            self._run('playlist', self._service().playlist(item_id))

    def _account_label(self):
        self.account_status.setText(('已登录：' + (self.session['nickname'] or self.session['uid'])
                                    if self.session else '登录网易云，查看创建、收藏和喜欢的歌单')
                                   + (' · 当前使用自定义服务' if self.base else ''))
        self.account_buttons['扫码登录网易云'].setVisible(not bool(self.session))
        self.direct_login_button.setVisible(not bool(self.session))
        for name in ('刷新歌单', '我喜欢的音乐', '退出登录'):
            self.account_buttons[name].setEnabled(bool(self.session))
        self.download_collection_button.setEnabled(bool(self.session))

    def _remember_changed(self, checked):
        try:
            if checked and self.session:
                self.cache.save_session(self.session)
                self.status.setText('独立会话已用Windows凭据保护保存。')
            elif not checked:
                self.cache.path('session.json').unlink(missing_ok=True)
        except (OSError, ValueError):
            self.status.setText('凭据保存／移除失败，未确认更改成功；旧加密会话可能仍在本机，请检查数据目录权限。')

    def _logout(self, show=True):
        self.cancel()
        self._restore_on_show = False
        self._session_warning = ''
        self.session = None
        self.sessionChanged.emit()
        self._job_private = False
        self._current_song = None
        self._current_playlist = None
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
            self.status.setText('已退出，独立凭据和个人缓存已清除。' if success else
                                '内存会话已退出，但本地凭据／个人缓存清理失败，请检查数据目录权限。')
        return success

    def logout(self):
        self._logout(True)

    def save_api(self):
        try:
            base = api_base(self.api_input.text())
            if base and not self.trust.isChecked():
                raise ValueError('须明确信任此服务接收账号凭据。')
            if base != self.base and not self._logout(False):
                self.status.setText('旧凭据清理失败，未更换API地址。')
                return
            self.cache.write('settings.json', dict(version=1, api=base))
            self.base = base
            self.sessionChanged.emit()
            self.api_input.setText(base)
            self._account_label()
            self.status.setText('连接方式已保存。' + ('扫码将通过自定义服务。' if base else '已恢复默认直连，可返回“我的歌单”扫码登录。'))
        except (OSError, ValueError):
            self.status.setText('接口未保存：请核对HTTPS／回环地址、信任选项及目录权限。')

    def _accept_session(self, session):
        self._qr_key = ''
        self.qr_timer.stop()
        self._clear_qr()
        self.session = session
        self.sessionChanged.emit()
        self._account_label()
        self.tabs.setCurrentIndex(2)
        self._session_warning = ''
        if self.remember.isChecked():
            try:
                self.cache.save_session(self.session)
            except (OSError, ValueError):
                self._session_warning = ' 本次登录有效，但无法加密记住登录；下次需重新登录。'
        self.fetch_collections()

    def _completed(self, kind, result):
        if kind=='session_recheck' and (not self._session_recheck or self._session_recheck[0]!=self._session_epoch):return
        if self._closed:
            return
        self._busy = False
        try:
            if kind == 'session_recheck':
                context,self._session_recheck=self._session_recheck,None
                if context and context[0]==self._session_epoch:
                    self.status.setText(context[1]+' 当前账号验证仍有效，请重试读取；已有登录和快照已保留。')
                return
            if kind in ('song', 'song_selected'):
                self._show_song(result, replace=kind == 'song')
                if not self.cache.save_snapshot('song', result['id'], result, self._job_private):
                    self.status.setText(self.status.text() + ' 上次可用歌词缓存已保留。')
            elif kind in ('playlist', 'likes'):
                self._show_playlist(result)
                saved = self.cache.save_snapshot('playlist' if kind == 'playlist' else 'likes', result['id'], result, self._job_private)
                self._refresh_snapshots()
                if not saved:
                    self.status.setText(self.status.text() + ' 当前部分结果未覆盖上次完整快照。')
            elif kind == 'collections':
                self.collections.clear()
                for category, entries in [('创建', result['created']), ('收藏', result['collected'])]:
                    for entry in entries:
                        item = QTreeWidgetItem([category, entry['title']])
                        item.setData(0, Qt.ItemDataRole.UserRole, entry['id'])
                        self.collections.addTopLevelItem(item)
                self.cache.save_snapshot('collections', self.session['uid'], result, True)
                self.status.setText(f'已加载{self.collections.topLevelItemCount()}个歌单，双击打开。' + '；'.join(result['warnings']) + self._session_warning)
                self.tabs.setCurrentIndex(2)
            elif kind == 'qr':
                self.qr_image.setPixmap(login_pixmap(result))
                self.qr_image.show()
                self._qr_key = result['key']
                self._qr_deadline = time.monotonic() + 180
                self.status.setText('请用手机网易云音乐 App 扫码，并在手机上确认登录。')
                self.qr_timer.start(3000)
            elif kind == 'qr_check':
                code = result['code']
                if code == 800:
                    self.cancel()
                    self.status.setText('二维码已过期，请重新扫码。')
                elif code in (801, 802):
                    self.status.setText('等待扫码。' if code == 801 else '已扫码，请在App中确认。')
                    self.qr_timer.start(3000)
                elif code == 803:
                    self._accept_session(result['session'])
        except ImportError:
            self.qr_timer.stop()
            self._qr_key = ''
            self._clear_qr()
            self.status.setText('二维码组件未安装，请用“启动桌宠.bat”重新启动以自动补齐依赖。')
        except (OSError, ValueError, TypeError, KeyError):
            self.status.setText('数据已返回，但显示或本地保存失败；未声称缓存／凭据保存成功。请检查接口格式和目录权限。')

    def _failed(self, kind, message, expired):
        if kind=='session_recheck' and (not self._session_recheck or self._session_recheck[0]!=self._session_epoch):return
        if self._closed:
            return
        self._busy = False
        if kind=='session_recheck':
            context,self._session_recheck=self._session_recheck,None
            if not context or context[0]!=self._session_epoch:return
            if not expired:
                self.status.setText(context[1]+' 暂时无法核实账号状态，已保留登录；可稍后重试。')
                return
            message='已重新核实，账号登录已失效，请重新登录。'
        elif expired and self.session and kind not in ('qr','qr_check'):
            self._session_recheck=(self._session_epoch,message)
            self._run('session_recheck',self._service().verify_session())
            self.status.setText('读取未成功，正在核实账号是否失效；权限错误不会直接清除登录。')
            return
        if expired:
            cleared = self._logout(False)
            if not cleared:
                message += ' 本地个人缓存清理失败，请检查目录权限。'
        else:
            self.qr_timer.stop()
            self._qr_key = ''
            self._clear_qr()
        self.status.setText(message + ('' if kind in ('qr', 'qr_check') else ' 上次成功快照不会被请求失败覆盖。'))

    def cancel(self):
        self._session_recheck = None
        self._browser_pending = False
        self.browser_recheck.hide()
        self.browser_status.hide()
        if self.browser_login is not None:
            self.browser_login.cancel()
        self.qr_timer.stop()
        self._qr_key = ''
        self._clear_qr()
        self.client.cancel()
        self._busy = False
        if not self._closed:
            self.status.setText('已取消；迟到响应不会绑定歌词或更新账号。')

    def shutdown(self):
        if not self._closed:
            self._closed = True
            self.cancel()

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._restore_on_show and self.session and not self._closed:
            self._restore_on_show = False
            self.fetch_collections()
