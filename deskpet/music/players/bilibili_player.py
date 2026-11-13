"""Bilibili-only playlist, owned WebView2 process and end-event queue control."""
import json
from pathlib import Path
import sys
import time
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QListWidget, QLineEdit, QComboBox, QCheckBox)
from deskpet.music.players.bilibili_links import video_url, load_web_tracks, EndLatch
from deskpet.music.tools.library import PlaybackQueue, MODES
from deskpet.ui.theme import style_combo
from deskpet.runtime.workers import worker_command


class BilibiliPlayer(QWidget):
    starting = Signal()
    playbackChanged = Signal(bool)
    accountReady = Signal(object)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.settings = owner.settings
        self.tracks = load_web_tracks(self.settings.value('bilibili_tracks', ''))
        self.queue = PlaybackQueue(self.settings.value('bilibili_mode', 'order'))
        self.queue.reverse = self.settings.value('bilibili_reverse', False, type=bool)
        saved_url = self.settings.value('bilibili_current_url', '')
        urls = [track['url'] for track in self.tracks]
        self.current_url = saved_url if saved_url in urls else ''
        if self.current_url:
            self.queue.reset(urls, urls.index(self.current_url))
        self.hidden = False
        self.active = self.playing = self.ready = self.closing = False
        self.requested_play = False
        self.play_intent_pending = False
        self.metrics = {}
        self.last_report = 0
        self.pending_load = None
        self.pending_account = None
        self.account_request = ''
        self.worker_args = []
        self.latch = EndLatch()
        self.buffer = ''
        self.diagnostic = {}
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.read_events)
        self.process.errorOccurred.connect(self.process_error)
        self.process.finished.connect(self.process_finished)
        self.process.readyReadStandardError.connect(lambda: self.process.readAllStandardError())
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(1000)
        self.watchdog.timeout.connect(self.check_report_age)
        self.watchdog.start()
        layout = QVBoxLayout(self)
        self.title = QLabel('添加 B站视频，一首结束后自动播放下一首')
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('B站视频链接；合集 / 收藏夹也可粘贴到这里')
        self.input.returnPressed.connect(self.add_link)
        row.addWidget(self.input, 1)
        add = QPushButton('添加链接')
        add.clicked.connect(self.add_link)
        row.addWidget(add)
        layout.addLayout(row)
        self.import_dialog = None
        import_lists = QPushButton('导入合集 / UP 主 / 我的收藏夹')
        import_lists.clicked.connect(lambda: self.open_import())
        layout.addWidget(import_lists)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.play_row(self.list.currentRow()))
        layout.addWidget(self.list, 1)
        reorder = QHBoxLayout()
        self.move_up_button = QPushButton('上移')
        self.move_up_button.clicked.connect(lambda: self.move_song(-1))
        reorder.addWidget(self.move_up_button)
        self.move_down_button = QPushButton('下移')
        self.move_down_button.clicked.connect(lambda: self.move_song(1))
        reorder.addWidget(self.move_down_button)
        self.reverse_toggle = QCheckBox('倒序播放')
        self.reverse_toggle.setToolTip('从当前歌曲往列表前面播放；未选歌曲时从最后一首开始。可配合列表循环；随机播放时不使用倒序。')
        self.reverse_toggle.setChecked(self.queue.reverse)
        self.reverse_toggle.toggled.connect(self.change_reverse)
        reorder.addWidget(self.reverse_toggle)
        layout.addLayout(reorder)
        self.list.currentRowChanged.connect(self.update_move_buttons)
        self.update_move_buttons()
        controls = QHBoxLayout()
        for name, callback in [('上一首', lambda: self.step(-1)), ('播放 / 暂停', self.toggle),
                                ('下一首', lambda: self.step(1))]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        tools = QHBoxLayout()
        self.mode = QComboBox()
        style_combo(self.mode)
        for key, name in MODES.items():
            self.mode.addItem(name, key)
        self.mode.setCurrentIndex(self.mode.findData(self.queue.mode))
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.reverse_toggle.setEnabled(self.queue.mode != 'shuffle')
        tools.addWidget(self.mode)
        for name, callback in [('移除', self.remove), ('显示网页', lambda: self.send({'cmd': 'show'})),
                                ('停止', self.stop)]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addLayout(tools)
        windows = QHBoxLayout()
        minimize = QPushButton('最小化到托盘')
        minimize.clicked.connect(lambda: self.send({'cmd': 'hide'}))
        windows.addWidget(minimize)
        layout.addLayout(windows)
        self.note = QLabel('网页声音使用 Windows 默认输出；登录或验证请在播放网页完成。')
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.note)
        self.render()
        self.alternate_toggle = QCheckBox('本地 / B站轮流循环')
        self.alternate_toggle.setToolTip('与音乐页当前本地歌单轮流播放，每边一首；切到 B站时默认收起网页，音乐继续。')
        self.alternate_toggle.setChecked(self.settings.value('music/alternate_sources', False, type=bool))
        self.alternate_toggle.toggled.connect(lambda enabled: self.owner.set_alternating(enabled))
        layout.insertWidget(1, self.alternate_toggle)
        if self.current_url:
            self.list.setCurrentRow(urls.index(self.current_url))
            track = self.tracks[urls.index(self.current_url)]
            self.title.setText(track['title'] or self.current_url)

    def render(self):
        selected = self.list.currentRow()
        self.list.clear()
        for track in self.tracks:
            self.list.addItem(track['title'] or track['url'].split('/video/')[1])
            self.list.item(self.list.count() - 1).setToolTip(track['url'])
        if selected >= 0:
            self.list.setCurrentRow(min(selected, len(self.tracks) - 1))

    def save(self):
        self.settings.setValue('bilibili_tracks', json.dumps(self.tracks, ensure_ascii=False))
        self.settings.setValue('bilibili_mode', self.queue.mode)
        self.settings.setValue('bilibili_reverse', self.queue.reverse)
        self.settings.setValue('bilibili_current_url', self.current_url)
        self.settings.sync()

    def add_link(self):
        try:
            url = video_url(self.input.text())
        except ValueError as error:
            from .bilibili_import import parse_source
            try:
                source = parse_source(self.input.text())
            except ValueError:
                self.note.setText(str(error))
                return False
            if source.kind == 'video':
                url = source.url
            else:
                self.open_import(self.input.text())
                return True
        if any(track['url'] == url for track in self.tracks):
            self.note.setText('这条视频已在歌单中')
            return False
        self.tracks.append({'url': url, 'title': ''})
        if self.active:
            urls = [track['url'] for track in self.tracks]
            self.queue.reset(urls, urls.index(self.current_url))
        self.input.clear()
        self.render()
        self.save()
        self.note.setText('已添加，双击歌单项或点击播放。多 P 视频可通过“导入合集”添加全部分 P。')
        return True

    def open_import(self, value=''):
        if self.import_dialog is None:
            from .bilibili_import_dialog import BilibiliImportDialog
            self.import_dialog = BilibiliImportDialog(self)
        self.import_dialog.show()
        self.import_dialog.raise_()
        self.import_dialog.activateWindow()
        if value and not self.import_dialog.service.active:
            self.import_dialog.input.setText(value)
            self.import_dialog.read_link()

    def add_imported_tracks(self, tracks):
        """Commit a complete read without starting/stopping playback or deleting songs."""
        incoming = load_web_tracks(json.dumps(tracks, ensure_ascii=False))
        existing = {track['url']: track for track in self.tracks}
        added = repeated = 0
        for track in incoming:
            if track['url'] in existing:
                repeated += 1
                if not existing[track['url']]['title'] and track['title']:
                    existing[track['url']]['title'] = track['title']
                continue
            self.tracks.append(track)
            existing[track['url']] = track
            added += 1
        if incoming:
            urls = [track['url'] for track in self.tracks]
            if self.current_url in urls:
                self.queue.reset(urls, urls.index(self.current_url))
            elif self.queue.paths:
                self.queue.reset(urls, -1)
            self.render()
            self.save()
        return added, repeated

    def change_mode(self):
        self.queue.mode = self.mode.currentData()
        self.queue.bag.clear()
        self.reverse_toggle.setEnabled(self.queue.mode != 'shuffle')
        self.save()

    def change_reverse(self, enabled):
        self.queue.reverse = bool(enabled)
        self.save()
        self.note.setText('已开启倒序播放，从当前歌曲往前播放；顺序播放到第一首后停止，列表循环会继续循环。'
                          if enabled else '已恢复从前往后播放。')

    def update_move_buttons(self, *_):
        row = self.list.currentRow()
        self.move_up_button.setEnabled(0 < row < len(self.tracks))
        self.move_down_button.setEnabled(0 <= row < len(self.tracks) - 1)

    def move_song(self, direction):
        row = self.list.currentRow()
        target = row + direction
        if direction not in (-1, 1) or not (0 <= row < len(self.tracks) and 0 <= target < len(self.tracks)):
            return
        self.tracks[row], self.tracks[target] = self.tracks[target], self.tracks[row]
        self.queue.reorder([track['url'] for track in self.tracks])
        self.render()
        self.list.setCurrentRow(target)
        self.save()
        self.note.setText('已上移，顺序已保存。' if direction < 0 else '已下移，顺序已保存。')

    def selected_or_start_row(self):
        row = self.list.currentRow()
        if row >= 0:
            return row
        return len(self.tracks) - 1 if self.queue.reverse and self.queue.mode != 'shuffle' else 0

    def remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        url = self.tracks.pop(row)['url']
        if url == self.current_url:
            self.stop()
            self.current_url = ''
            self.queue.reset([track['url'] for track in self.tracks], -1)
        elif self.current_url:
            urls = [track['url'] for track in self.tracks]
            self.queue.reset(urls, urls.index(self.current_url) if self.current_url in urls else 0)
        self.render()
        self.save()

    def play_row(self, row):
        if not 0 <= row < len(self.tracks):
            self.note.setText('请先添加 B站视频链接')
            return
        self.queue.reset([track['url'] for track in self.tracks], row)
        self.start_track(row)

    def start_track(self, index):
        if not 0 <= index < len(self.queue.paths):
            return
        self.queue.index = index
        selected = video_url(self.queue.paths[index])
        restart = self.active and self.current_url == selected
        self.current_url = selected
        row = next((i for i, track in enumerate(self.tracks) if track['url'] == selected), -1)
        if row >= 0:
            self.list.setCurrentRow(row)
        title = next((track['title'] for track in self.tracks if track['url'] == self.current_url), '')
        self.title.setText(title or self.current_url)
        self.latch.reset(uuid.uuid4().hex)
        self.metrics = {}
        self.last_report = 0
        self.active, self.playing = True, False
        self.requested_play = True
        self.play_intent_pending = True
        self.starting.emit()
        self.playbackChanged.emit(False)
        alternating = getattr(self.owner, 'alternating', None)
        self.pending_load = {'cmd': 'load', 'url': self.current_url, 'token': self.latch.token,
                             'volume': self.owner.volume.value() / 100, 'restart': restart, 'autoplay': True,
                             'background': bool(alternating and alternating.enabled)}
        if alternating is not None:
            alternating.remember('web', self.current_url)
        self.save()
        self.note.setText('正在打开 B站网页；如果未自动播放，请在网页点一次播放。')
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.start_process()
        elif self.ready and not self.closing:
            self.send_pending()

    def start_process(self):
        self.ready = self.closing = False
        self.hidden = bool(self.pending_load and self.pending_load.get('background')) or bool(self.pending_account and not self.pending_load)
        self.buffer = ''
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('PYTHONUNBUFFERED', '1')
        self.process.setProcessEnvironment(environment)
        program, arguments = worker_command('web')
        self.process.setProgram(program)
        self.process.setArguments(arguments + self.worker_args + (['--start-hidden'] if self.hidden else []))
        self.process.start()

    def send(self, value):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write((json.dumps(value) + '\n').encode('utf-8'))

    def send_pending(self):
        if self.pending_load:
            self.send(self.pending_load)
            self.pending_load = None
        if self.pending_account:
            self.send(self.pending_account)
            self.pending_account = None

    def request_import_account(self, request, login=False):
        self.account_request = request
        self.pending_account = dict(cmd='import-account', request=request, login=bool(login))
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.start_process()
        elif self.ready and not self.closing:
            self.send_pending()

    def cancel_import_account(self, request):
        if self.account_request == request:
            self.account_request = ''
            self.pending_account = None
            self.send(dict(cmd='cancel-import-account', request=request))

    def account_error(self):
        if self.account_request:
            request, self.account_request = self.account_request, ''
            self.pending_account = None
            self.accountReady.emit(dict(request=request, error='B站播放网页已关闭或无法启动，请重新读取。'))

    def toggle(self):
        selected = self.list.currentRow()
        if (self.active and 0 <= selected < len(self.tracks)
                and self.tracks[selected]['url'] != self.current_url):
            self.play_row(selected)
        elif not self.active or (not self.pending_load and self.process.state() == QProcess.ProcessState.NotRunning):
            self.play_row(self.selected_or_start_row())
        else:
            self.set_playing(not self.requested_play)

    def set_playing(self, playing):
        """Idempotent chat controls; pause also wins during initial worker boot."""
        self.requested_play = bool(playing)
        self.play_intent_pending = True
        if not self.active or (not self.pending_load and self.process.state() == QProcess.ProcessState.NotRunning):
            if playing:
                self.play_row(self.selected_or_start_row())
            return
        if self.pending_load is not None:
            self.pending_load['autoplay'] = bool(playing)
        elif self.ready and not self.closing:
            self.send({'cmd':'play' if playing else 'pause'})

    def step(self, direction):
        alternating = getattr(self.owner, 'alternating', None)
        if alternating is not None and alternating.advance('web', direction):
            return
        if not self.queue.paths:
            self.play_row(self.selected_or_start_row())
            return
        index = self.queue.advance(direction)
        if index is not None:
            self.start_track(index)

    def read_events(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if not line.startswith('TIANYI_WEB '):
                continue
            try:
                value = json.loads(line[len('TIANYI_WEB '):])
            except ValueError:
                continue
            if isinstance(value, dict):
                self.handle_event(value)
        self.buffer = self.buffer[-65536:]

    def handle_event(self, value):
        kind = value.get('type')
        if kind == 'import-account':
            if value.get('request') == self.account_request:
                self.account_request = ''
                self.accountReady.emit(value)
            return
        if kind == 'visibility':
            self.hidden = bool(value.get('hidden'))
            if self.hidden:
                self.note.setText('播放网页已收起到桌宠托盘，音乐继续；点击“显示网页”可恢复。')
            return
        if kind == 'diagnostic':
            self.diagnostic = value
            return
        if kind == 'ready':
            self.ready = True
            self.send_pending()
            return
        if kind == 'fatal':
            self.account_error()
            self.stop()
            self.note.setText(value.get('message', '网页播放器不可用'))
            return
        if not self.active or value.get('token') != self.latch.token:
            return
        if kind in ('waiting', 'error'):
            self.playing = False
            self.playbackChanged.emit(False)
            self.note.setText(value.get('message', '请检查播放网页'))
            return
        if kind != 'state':
            return
        self.metrics = value
        if 'requested_play' in value:
            requested = bool(value['requested_play'])
            if requested == self.requested_play:
                self.play_intent_pending = False
            elif not self.play_intent_pending:
                self.requested_play = requested
        self.last_report = time.monotonic()
        self.playing = bool(value.get('playing'))
        title = str(value.get('title', ''))[:200]
        if title:
            self.title.setText(title)
            for track in self.tracks:
                if track['url'] == self.current_url and title != track['title']:
                    track['title'] = title
                    self.render()
                    self.save()
        self.playbackChanged.emit(self.playing)
        if value.get('error'):
            self.note.setText('网页视频无法播放，请查看网页提示或手动切下一首')
        elif self.playing and value.get('muted'):
            self.note.setText('视频正在静音播放，请在网页取消静音；结束后会自动切歌。')
        elif self.playing:
            self.note.setText('网页正在播放，结束后自动切下一首；声音使用 Windows 默认输出。')
        elif value.get('starting_from_zero'):
            self.note.setText('正在从头播放，纠正网页历史续播进度…')
        elif value.get('restoring_position'):
            self.note.setText('网页进度发生跳转，正在接回刚才的播放位置…')
        elif not value.get('ended'):
            self.note.setText('视频已暂停；若网页阻止自动播放，请在网页点一次播放。')
        if self.requested_play and self.latch.accept(value):
            alternating = getattr(self.owner, 'alternating', None)
            if alternating is not None and alternating.advance('web'):
                return
            index = self.queue.advance(ended=True)
            if index is None:
                self.stop()
                self.note.setText('B站歌单已播完，播放网页已关闭')
            else:
                self.start_track(index)

    def stop(self, *_):
        self.active = self.playing = False
        self.requested_play = False
        self.play_intent_pending = False
        self.pending_load = None
        self.metrics = {}
        self.playbackChanged.emit(False)
        self.note.setText('网页播放已停止')
        self.closing = True
        self.send({'cmd': 'close'})
        QTimer.singleShot(2500, self.kill_if_closing)

    def kill_if_closing(self):
        if self.closing and not self.active and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()

    def shutdown(self):
        if self.import_dialog is not None:
            self.import_dialog.shutdown()
        self.stop()
        if not self.process.waitForFinished(2000):
            self.process.kill()
            self.process.waitForFinished(1000)

    def process_finished(self, *_):
        self.ready = False
        if (self.active and self.pending_load) or (self.pending_account and self.closing):
            self.start_process()
        elif self.active:
            self.active = self.playing = False
            self.playbackChanged.emit(False)
            self.note.setText('播放网页已关闭，自动播放已停止')
            self.account_error()
        else:
            self.account_error()

    def process_error(self, *_):
        if self.process.error() == QProcess.ProcessError.FailedToStart:
            self.account_error()
            self.active = self.playing = False
            self.playbackChanged.emit(False)
            self.note.setText('无法启动网页窗口，请重新运行启动脚本安装网页依赖')

    def check_report_age(self):
        if self.playing and time.monotonic() - self.last_report > 3:
            self.playing = False
            self.playbackChanged.emit(False)
