"""Lazy music tools with one source clock for lyrics and beat-driven motion."""
import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTabWidget, QLabel,
                               QMessageBox)
from music_tools.clock import playback_snapshot
from ui_theme import apply_light_palette


class MusicCompanion(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        from music_lyrics import LyricsController
        from music_beats import BeatController
        self.pet = pet
        self.root = pet.panel.data_dir / 'music-companion'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lyrics = LyricsController(pet, self.root, self)
        self.beats = BeatController(self.root, self)
        from music_tools.preparation import MusicPreparation
        self.preparation = MusicPreparation(self)
        self.window = self.cloud = None
        self.playback = self.downloads = None
        self.beat = None
        self._source = ''
        self._closed = False
        self.snapshot = playback_snapshot(pet.panel)
        self.bindings_path = self.root / 'source-bindings.json'
        try:
            raw = json.loads(self.bindings_path.read_text(encoding='utf-8'))
            self.bindings = {key: value for key, value in raw.items()
                             if isinstance(key, str) and key.isdigit() and isinstance(value, str)
                             and value.startswith(('local:', 'bilibili:'))} if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.bindings = {}
        self.lyrics.bound.connect(self.remember_binding)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def tick(self):
        if self._closed:
            return
        self.snapshot = playback_snapshot(self.pet.panel)
        current = self.snapshot
        if current.source_key != self._source:
            self._source = current.source_key
            self.beats.set_source(self._source)
        self.lyrics.update(current.source_key, current.position_ms,
                           current.playing, current.duration_ms, valid=current.valid)
        self.beat = self.beats.sample(current.position_ms, current.playing) if current.valid else None
        if self.window is not None:
            self.current_label.setText('当前音源：' + (current.title or '未选择歌曲'))

    def open(self, page=0):
        if self.window is None:
            from netease_music import NeteaseWidget
            from compact_ui import COMPACT_STYLE
            self.window = QWidget(self.pet, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
            self.window.setWindowTitle('天依 · 网易云、歌词与节拍')
            self.window.resize(760, 740)
            apply_light_palette(self.window)
            self.window.setStyleSheet(COMPACT_STYLE)
            layout = QVBoxLayout(self.window)
            self.current_label = QLabel()
            self.current_label.setTextFormat(Qt.TextFormat.PlainText)
            self.current_label.setWordWrap(True)
            layout.addWidget(self.current_label)
            self.tabs = QTabWidget()
            layout.addWidget(self.tabs)
            self.cloud = NeteaseWidget(self.root / 'netease', self.window)
            self.cloud.lyricsReady.connect(self.online_lyrics)
            self.cloud.bindRequested.connect(self.bind_cached)
            self.cloud.playBoundRequested.connect(self.play_bound)
            from netease_music.playback import NeteasePlayback
            from netease_music.download_queue import NeteaseDownloads
            self.playback = NeteasePlayback(self, self.cloud)
            self.downloads = NeteaseDownloads(self, self.cloud)
            self.cloud.playRequested.connect(self.playback.play)
            self.cloud.downloadRequested.connect(self.downloads.start)
            self.cloud.playlistDownloadRequested.connect(self.downloads.start_playlist)
            self.cloud.transportRequested.connect(self.control_transport)
            self.cloud.modeRequested.connect(lambda mode: self.pet.panel.mode_choice.setCurrentIndex(
                self.pet.panel.mode_choice.findData(mode)))
            self.pet.panel.mode_choice.currentIndexChanged.connect(self.sync_cloud_mode)
            self.sync_cloud_mode()
            self.tabs.addTab(self.cloud, '网易云')
            self.tabs.addTab(self.lyrics.create_widget(self.window), '歌词字幕')
            self.tabs.addTab(self.beats.create_widget(self.window), '节拍跟随')
        self.tick()
        self.tabs.setCurrentIndex(max(0, min(2, page)))
        self.pet.toolbar.hide()
        self.pet.reveal_dock()
        from desktop_pet import clamp_near
        clamp_near(self.pet, self.window)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def control_transport(self, action):
        if action == 'toggle':
            self.pet.panel.toggle()
        elif action in ('previous', 'next'):
            self.pet.panel.step(-1 if action == 'previous' else 1)

    def sync_cloud_mode(self, *_):
        if self.cloud is not None:
            choice = self.cloud.play_mode
            choice.blockSignals(True)
            choice.setCurrentIndex(choice.findData(self.pet.panel.queue.mode))
            choice.blockSignals(False)

    def notify(self, text):
        self.pet.bubble.say(text, 8000)

    def online_lyrics(self, song_id, title, lrc):
        try:
            self.lyrics.cache_online(song_id, title, lrc)
            self.bind_lyrics(song_id, title, lrc)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.notify('歌词未绑定：' + str(error))

    def bind_cached(self, song_id, title):
        try:
            cached = self.lyrics.get_cached(song_id)
            if cached:
                self.bind_lyrics(song_id, cached['title'], cached['body'])
            else:
                self.notify('尚未缓存这首歌的歌词，请先在网易云页获取。')
        except (OSError, ValueError, sqlite3.Error) as error:
            self.notify('歌词未绑定：' + str(error))

    def bind_lyrics(self, song_id, title, lrc):
        current = playback_snapshot(self.pet.panel)
        if not current.source_key:
            self.notify('歌词已缓存。先选择本地歌曲或 B站视频，再在歌词字幕页绑定。')
            return
        question = f'把《{title}》的歌词绑定到以下音源？\n\n{current.title}\n\n请确认歌曲版本一致；Live、翻唱或剪辑版可能需要不同歌词。'
        if QMessageBox.question(self.window, '确认歌词版本', question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.lyrics.import_online(song_id, title, lrc, current.source_key)
        self.tick()
        self.notify('已绑定歌词，可在“歌词字幕”页调整时间偏移。')

    def remember_binding(self, song_id, source_key):
        if not source_key.startswith(('local:', 'bilibili:')):
            return
        self.bindings[str(song_id)] = source_key
        try:
            temporary = self.bindings_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.bindings, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.bindings_path)
        except OSError:
            self.notify('歌词已绑定，但播放音源映射未能保存；请检查数据目录权限。')

    def play_bound(self, song_id):
        key = self.bindings.get(str(song_id), '')
        panel = self.pet.panel
        if key.startswith('local:'):
            path = key[6:]
            if not Path(path).is_file():
                self.notify('绑定的本地文件已不存在，请重新绑定。')
                return
            panel.activate_local()
            panel.queue.reset([path], 0)
            panel.queue_owner = ''
            panel.start_track(0)
        elif key.startswith('bilibili:'):
            try:
                _, identifier, part = key.split(':')
                from bilibili_links import video_url
                url = video_url(f'https://www.bilibili.com/video/{identifier}?p={part}')
            except ValueError:
                self.notify('音源绑定已失效，请重新绑定。')
                return
            web = panel.bilibili
            web.queue.reset([url], 0)
            web.start_track(0)
        else:
            self.notify('这首歌尚未绑定音源。先播放对应本地歌曲或 B站视频，再获取歌词并确认绑定。')

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.preparation.cancel()
        if self.playback is not None:
            self.playback.deactivate()
        if self.downloads is not None:
            self.downloads.cancel()
        if self.cloud is not None:
            self.cloud.shutdown()
        self.beats.shutdown()
        self.lyrics.shutdown()
        if self.window is not None:
            self.window.hide()
