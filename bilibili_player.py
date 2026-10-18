"""Bilibili-only playlist, owned WebView2 process and end-event queue control."""
import json
from pathlib import Path
import sys
import time
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal, Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QListWidget, QLineEdit, QComboBox)
from bilibili_links import video_url, load_web_tracks, EndLatch
from music_library import PlaybackQueue, MODES
from ui_theme import style_combo
from worker_command import worker_command


class BilibiliPlayer(QWidget):
    starting = Signal()
    playbackChanged = Signal(bool)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.settings = owner.settings
        self.tracks = load_web_tracks(self.settings.value('bilibili_tracks', ''))
        self.queue = PlaybackQueue(self.settings.value('bilibili_mode', 'order'))
        self.current_url = ''
        self.hidden = False
        self.active = self.playing = self.ready = self.closing = False
        self.metrics = {}
        self.last_report = 0
        self.pending_load = None
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
        self.input.setPlaceholderText('https://www.bilibili.com/video/BV…')
        self.input.returnPressed.connect(self.add_link)
        row.addWidget(self.input, 1)
        add = QPushButton('添加链接')
        add.clicked.connect(self.add_link)
        row.addWidget(add)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.play_row(self.list.currentRow()))
        layout.addWidget(self.list, 1)
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
        self.settings.sync()

    def add_link(self):
        try:
            url = video_url(self.input.text())
        except ValueError as error:
            self.note.setText(str(error))
            return False
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
        self.note.setText('已添加，双击歌单项或点击播放。短链接请先在浏览器展开。')
        return True

    def change_mode(self):
        self.queue.mode = self.mode.currentData()
        self.queue.bag.clear()
        self.save()

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
        title = next((track['title'] for track in self.tracks if track['url'] == self.current_url), '')
        self.title.setText(title or self.current_url)
        self.latch.reset(uuid.uuid4().hex)
        self.metrics = {}
        self.last_report = 0
        self.active, self.playing = True, False
        self.starting.emit()
        self.playbackChanged.emit(False)
        self.pending_load = {'cmd': 'load', 'url': self.current_url, 'token': self.latch.token,
                             'volume': self.owner.volume.value() / 100, 'restart': restart}
        self.note.setText('正在打开 B站网页；如果未自动播放，请在网页点一次播放。')
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.start_process()
        elif self.ready and not self.closing:
            self.send_pending()

    def start_process(self):
        self.ready = self.closing = False
        self.hidden = False
        self.buffer = ''
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONIOENCODING', 'utf-8')
        environment.insert('PYTHONUNBUFFERED', '1')
        self.process.setProcessEnvironment(environment)
        program, arguments = worker_command('web')
        self.process.setProgram(program)
        self.process.setArguments(arguments + self.worker_args)
        self.process.start()

    def send(self, value):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.write((json.dumps(value) + '\n').encode('utf-8'))

    def send_pending(self):
        if self.pending_load:
            self.send(self.pending_load)
            self.pending_load = None

    def toggle(self):
        if not self.active:
            self.play_row(max(0, self.list.currentRow()))
        else:
            self.send({'cmd': 'pause' if self.playing else 'play'})

    def step(self, direction):
        if not self.queue.paths:
            self.play_row(max(0, self.list.currentRow()))
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
        elif not value.get('ended'):
            self.note.setText('视频已暂停；若网页阻止自动播放，请在网页点一次播放。')
        if self.latch.accept(value):
            index = self.queue.advance(ended=True)
            if index is None:
                self.stop()
                self.note.setText('B站歌单已播完，播放网页已关闭')
            else:
                self.start_track(index)

    def stop(self, *_):
        self.active = self.playing = False
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
        self.stop()
        if not self.process.waitForFinished(2000):
            self.process.kill()
            self.process.waitForFinished(1000)

    def process_finished(self, *_):
        self.ready = False
        if self.active and self.pending_load:
            self.start_process()
        elif self.active:
            self.active = self.playing = False
            self.playbackChanged.emit(False)
            self.note.setText('播放网页已关闭，自动播放已停止')

    def process_error(self, *_):
        if self.process.error() == QProcess.ProcessError.FailedToStart:
            self.active = self.playing = False
            self.playbackChanged.emit(False)
            self.note.setText('无法启动网页窗口，请重新运行启动脚本安装网页依赖')

    def check_report_age(self):
        if self.playing and time.monotonic() - self.last_report > 3:
            self.playing = False
            self.playbackChanged.emit(False)
