"""Luo Tianyi interactive desktop pet with local music and opt-in startup."""
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == 'win32':
    os.environ.setdefault('QT_MEDIA_BACKEND', 'windows')

from PySide6.QtCore import QSettings, QTimer, QUrl, QStandardPaths, QLockFile, Signal
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMenu, QMessageBox, QWidget, QInputDialog, QProgressDialog,
)


def clock(ms):
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02}:{seconds % 60:02}"


from pet_store import PetStore
from compact_ui import build
from desktop_pet import DesktopPet
from music_library import MusicLibrary, PlaybackQueue, MODES
from windows_startup import WindowsStartup
from audio_routing import device_id
from remote_audio import AudioEngine
from character_packs import character_directory


class MusicPanel(QWidget):
    songChanged = Signal(str)

    def set_song_title(self, title):
        self.song_title.setText(title)
        self.songChanged.emit(title)

    def __init__(self, pet, data_dir=None, startup=None, settings=None, characters_dir=None):
        super().__init__()
        self.pet = pet
        self.settings = settings if settings is not None else QSettings("TianyiPet", "Prototype")
        self.startup = startup or WindowsStartup()
        data_dir = Path(data_dir) if data_dir else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir
        self.characters_dir = Path(characters_dir) if characters_dir is not None else character_directory()
        self.engine = None
        self.store = PetStore(data_dir / "pet.db")
        self.last_tick = time.monotonic()
        self.last_position = None
        self.last_source = None
        self.pending_seek = None
        self.autoplay_requested = False
        self.failed_paths = set()
        self.queue_owner = ''
        self.last_save = time.monotonic()
        self.playback_source = 'local'
        self.setWindowTitle("天依音乐 · 第一阶段原型")
        self.resize(460, 440)
        legacy = self.settings.value('paths', [])
        self.library = MusicLibrary(self.settings.value('library_v1', ''),
                                    legacy if isinstance(legacy, list) else [legacy])
        self.queue = PlaybackQueue(self.settings.value('play_mode', 'order'))
        self._audio = self._player = self._audio_router = None
        self._restore_request = None
        build(self)
        self.bilibili.starting.connect(self.activate_web)
        self.bilibili.playbackChanged.connect(self.web_playback_changed)
        self.volume.valueChanged.connect(lambda value: self.bilibili.send({'cmd': 'volume', 'value': value / 100}))
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.sample)
        self.progress_timer.start(1000)
        self.list.itemDoubleClicked.connect(lambda _: self.play_row(self.list.currentRow()))
        self.setAcceptDrops(True)
        self.render_library()
        self.refresh_startup()
        self.refresh_growth()
        self.restore_playback()
        self.tabs.currentChanged.connect(lambda index: self.ensure_audio() if index == 2 else None)
        self.tabs.currentChanged.connect(lambda index: self.pet.refresh_characters() if index == 2
                                        and hasattr(self.pet, 'refresh_characters') else None)

    def ensure_audio(self):
        """Windows endpoint discovery can be slow; perform it on first use."""
        if self._player is not None:
            return
        self.engine = AudioEngine(self.settings, self.data_dir, self)
        self._audio, self._player, self._audio_router = self.engine.audio, self.engine.player, self.engine.router
        self._player.durationChanged.connect(self.duration_changed)
        self._player.seekableChanged.connect(lambda _: self.duration_changed(self._player.duration()))
        self._player.positionChanged.connect(self.position_changed)
        self._player.playbackStateChanged.connect(self.state_changed)
        self._player.mediaStatusChanged.connect(self.media_changed)
        self._player.errorOccurred.connect(self.audio_error)
        self._audio_router.changed.connect(self.refresh_audio_outputs)
        self.loading = QProgressDialog('正在准备音频设备，首次播放可能需要几秒…', '', 0, 0, self)
        self.loading.setCancelButton(None)
        self.loading.setWindowTitle('正在准备播放')
        self.loading.setMinimumDuration(0)
        self.loading.setAutoClose(False)
        self.engine.loadingChanged.connect(lambda loading: self.loading.show() if loading else self.loading.hide())
        self.engine.failed.connect(self.audio_helper_failed)
        self._audio.setVolume(self.volume.value() / 100)
        self.engine.start()
        if self._restore_request:
            path, position = self._restore_request
            self._restore_request = None
            self.pending_seek = position
            self._player.setSource(QUrl.fromLocalFile(path))

    def audio_helper_failed(self, message):
        self.autoplay_requested = False
        self.pet.playing = False
        self.status.setText(message)

    def shutdown_audio(self):
        if self.engine is not None:
            self.engine.shutdown()

    @property
    def player(self):
        self.ensure_audio()
        return self._player

    @property
    def audio(self):
        self.ensure_audio()
        return self._audio

    @property
    def audio_router(self):
        self.ensure_audio()
        return self._audio_router

    def set_volume(self, value):
        if self._audio is not None:
            self._audio.setVolume(value / 100)

    @property
    def paths(self):
        return self.library.paths

    def current_path(self):
        if self._player is None:
            return self._restore_request[0] if self._restore_request else ''
        path = self._player.source().toLocalFile()
        return str(Path(path).resolve()) if path else ''

    def activate_web(self):
        self.playback_source = 'web'
        self.autoplay_requested = False
        if self._player is not None:
            self._player.pause()
        self.last_source = self.last_position = None
        self.pet.playing = False

    def activate_local(self):
        self.playback_source = 'local'
        if self.bilibili.active:
            self.bilibili.stop()
        self.last_source = self.last_position = None

    def web_playback_changed(self, playing):
        if self.playback_source != 'web':
            return
        if self.pet.playing != playing:
            self.last_position = None
        self.pet.playing = playing
        self.play_button.setText('暂停' if playing else '播放')
        self.set_song_title(self.bilibili.title.text())
        self.song_meta.setText('B站网页 · ' + MODES[self.bilibili.queue.mode])
        self.status.setText('B站播放中' if playing else 'B站已暂停或正在加载')

    def reset_audio_sample(self):
        self.last_position = None
        self.last_tick = time.monotonic()

    def refresh_audio_outputs(self):
        router = self.audio_router
        self.output_choice.blockSignals(True)
        self.output_choice.clear()
        self.output_choice.addItem('跟随系统默认输出', '')
        for device in router.outputs:
            self.output_choice.addItem(device.description(), device_id(device))
        if router.preferred and self.output_choice.findData(router.preferred) < 0:
            name = self.settings.value('audio_output_name', '上次选择的设备')
            self.output_choice.addItem(name + '（未连接）', router.preferred)
        self.output_choice.setCurrentIndex(max(0, self.output_choice.findData(router.preferred)))
        self.output_choice.blockSignals(False)
        self.output_note.setText(router.summary)
        self.output_note.setToolTip(router.summary)

    def choose_audio_output(self, index):
        if index >= 0:
            self.audio_router.choose(self.output_choice.itemData(index))

    def refresh_startup(self):
        self.startup_toggle.blockSignals(True)
        try:
            self.startup_toggle.setChecked(self.startup.enabled())
            self.startup_toggle.setEnabled(self.startup.supported)
        except OSError as error:
            self.startup_note.setText('暂时无法读取开机自启设置：' + str(error))
            self.startup_toggle.setEnabled(False)
        finally:
            self.startup_toggle.blockSignals(False)

    def toggle_startup(self, checked):
        try:
            self.startup.set_enabled(checked)
            self.status.setText('已开启开机自启' if checked else '已关闭开机自启')
        except OSError as error:
            self.status.setText('自启设置失败：' + str(error))
        self.refresh_startup()

    def render_library(self, selected=None):
        self.playlist_choice.blockSignals(True)
        self.playlist_choice.clear()
        for playlist in self.library.playlists:
            self.playlist_choice.addItem(playlist['name'], playlist['id'])
        self.playlist_choice.setCurrentIndex(self.playlist_choice.findData(self.library.active_id))
        self.playlist_choice.blockSignals(False)
        self.list.clear()
        for path in self.paths:
            exists = Path(path).is_file()
            self.list.addItem(('' if exists else '失效 · ') + Path(path).stem)
            self.list.item(self.list.count() - 1).setToolTip(path)
        self.list_stack.setCurrentIndex(1 if self.paths else 0)
        self.queue_label.setText(f'歌单 · {len(self.paths)} 首' if self.paths else '歌单')
        current = self.current_path()
        if selected is not None and 0 <= selected < len(self.paths):
            self.list.setCurrentRow(selected)
        elif current in self.paths:
            self.list.setCurrentRow(self.paths.index(current))
        self.filter_songs(self.search.text())

    def store_library(self):
        if self.queue_owner == self.library.active_id:
            current = self.current_path()
            paths = list(self.paths)
            if current in paths:
                self.queue.reset(paths, paths.index(current))
            elif current:
                self.queue.reset([current] + paths, 0)
        self.settings.setValue('library_v1', self.library.dumps())
        self.settings.sync()

    def choose_playlist(self, index):
        identifier = self.playlist_choice.itemData(index)
        if identifier:
            self.library.active_id = identifier
            self.render_library()
            self.store_library()

    def new_playlist(self):
        name, ok = QInputDialog.getText(self, '新建歌单', '歌单名称')
        if ok and name.strip():
            self.library.create(name)
            self.render_library()
            self.store_library()

    def manage_playlist(self):
        menu = QMenu(self)
        rename = menu.addAction('重命名歌单')
        delete = menu.addAction('删除歌单')
        delete.setEnabled(len(self.library.playlists) > 1)
        action = menu.exec(self.playlist_manage.mapToGlobal(self.playlist_manage.rect().bottomLeft()))
        if action == rename:
            name, ok = QInputDialog.getText(self, '重命名歌单', '歌单名称', text=self.library.active['name'])
            if ok and name.strip():
                self.library.rename(name)
        elif action == delete:
            result = QMessageBox.question(self, '删除歌单', '只删除这个歌单，磁盘上的歌曲会保留。继续吗？')
            if result != QMessageBox.StandardButton.Yes:
                return
            self.library.delete()
        else:
            return
        self.render_library()
        self.store_library()

    def filter_songs(self, text):
        text = text.casefold().strip()
        for row, path in enumerate(self.paths):
            self.list.item(row).setHidden(text not in Path(path).stem.casefold())

    def remove_songs(self):
        rows = [index.row() for index in self.list.selectedIndexes()]
        if not rows:
            self.status.setText('先选择要从歌单移除的歌曲')
            return
        self.library.remove(rows)
        self.render_library()
        self.store_library()
        self.status.setText(f'已从歌单移除 {len(rows)} 首，磁盘文件保留')

    def move_song(self, direction):
        row = self.list.currentRow()
        target = row + direction
        if 0 <= row < len(self.paths) and 0 <= target < len(self.paths):
            self.paths[row], self.paths[target] = self.paths[target], self.paths[row]
            self.render_library(target)
            self.store_library()

    def set_mode(self, index):
        self.queue.mode = self.mode_choice.itemData(index)
        self.queue.bag = []
        self.settings.setValue('play_mode', self.queue.mode)
        self.song_meta.setText('本地 MP3 · ' + MODES[self.queue.mode])

    def duration_changed(self, duration):
        if self.playback_source == 'web':
            return
        self.seek.setRange(0, duration)
        ready = self.player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia,
                                             QMediaPlayer.MediaStatus.BufferingMedia,
                                             QMediaPlayer.MediaStatus.BufferedMedia)
        if self.pending_seek is not None and duration > 0 and self.player.isSeekable() and ready:
            position = min(self.pending_seek, duration)
            self.pending_seek = None
            self.last_position = None
            self.player.setPosition(position)

    def restore_playback(self):
        saved_path = self.settings.value('current_path', '')
        path = str(Path(saved_path).resolve()) if saved_path else ''
        known = {p for playlist in self.library.playlists for p in playlist['paths']}
        if path not in known or not Path(path).is_file():
            return
        try:
            saved_queue = json.loads(self.settings.value('current_queue', '[]'))
            paths = [p for p in saved_queue if isinstance(p, str) and p in known]
        except (ValueError, TypeError):
            paths = []
        if path not in paths:
            paths.append(path)
        self.queue.reset(paths, paths.index(path))
        self.pending_seek = max(0, int(self.settings.value('current_position', 0)))
        self._restore_request = (path, self.pending_seek)
        self.set_song_title(Path(path).stem)
        self.status.setText('已恢复上次歌曲，点击播放继续')

    def seek_to(self):
        self.last_position = None
        if self.playback_source == 'web':
            self.bilibili.send({'cmd': 'seek', 'position': self.seek.value() / 1000})
            return
        self.player.setPosition(self.seek.value())

    def refresh_growth(self):
        pet = self.store.pet()
        stats = self.store.stats()
        self.growth.setText(
            f"等级 {pet['level']} · 经验 {pet['xp']} · 音符 {pet['notes']}\n"
            f"饱食度 {pet['hunger']}/100 · 心情 {pet['mood']}/100\n"
            f"听歌：今日 {clock(int(stats['today'] * 1000))} / "
            f"本周 {clock(int(stats['week'] * 1000))} / 累计 {clock(int(stats['total'] * 1000))}"
        )
        self.experience.setRange(0, 50 + 20 * (pet['level'] - 1))
        self.experience.setValue(pet['xp'])
        if hasattr(self.pet, 'toolbar'):
            self.pet.toolbar.refresh()
        previous = getattr(self, 'previous_level', pet['level'])
        if pet['level'] > previous and hasattr(self.pet, 'react'):
            self.pet.react('happy', 3, f"升级啦！现在是 {pet['level']} 级！")
        self.previous_level = pet['level']

    def feed(self, food):
        success, message = self.store.feed(food)
        self.status.setText(message)
        if hasattr(self.pet, 'feed_reaction'):
            self.pet.feed_reaction(success, message)
        self.refresh_growth()

    def sample(self):
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now
        position = self._player.position() if self._player is not None else 0
        source = self.current_path()
        playing = self._player is not None and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        audible = self._audio is not None and self._audio.volume() > 0 and not self._audio.isMuted()
        if self.playback_source == 'web':
            metrics = self.bilibili.metrics
            source = self.bilibili.current_url
            position = round(float(metrics.get('position', 0)) * 1000)
            playing = (self.bilibili.active and bool(metrics.get('playing')) and
                       now - self.bilibili.last_report < 2.5)
            audible = bool(metrics.get('volume', 0) > 0 and not metrics.get('muted'))
            duration = round(float(metrics.get('duration', 0)) * 1000)
            self.seek.setRange(0, duration)
            self.position_changed(position)
            self.time.setText(f'{clock(position)} / {clock(duration)}')
        if 0 < elapsed <= 3:
            self.store.tick_running(elapsed)
            if (playing and source and source == self.last_source and self.last_position is not None
                    and not self.seek.isSliderDown()):
                advance = (position - self.last_position) / 1000
                if 0 < advance <= elapsed + 0.5:
                    self.store.record(source, min(elapsed, advance),
                                      audible)
        self.last_position = position if playing else None
        self.last_source = source
        self.refresh_growth()
        if now - self.last_save >= 15:
            self.save()
            self.last_save = now

    def import_paths(self, paths):
        candidates = []
        for item in paths:
            path = Path(item)
            if path.is_dir():
                try:
                    candidates.extend(str(p) for p in path.iterdir() if p.is_file() and p.suffix.lower() == '.mp3')
                except OSError as error:
                    self.status.setText('无法读取文件夹：' + str(error))
            elif path.is_file():
                candidates.append(str(path))
        count = self.library.add(candidates)
        self.render_library()
        self.store_library()
        self.status.setText(f'已添加 {count} 首歌曲')

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 MP3", "", "MP3 音频 (*.mp3)")
        self.import_paths(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '添加文件夹中的 MP3')
        if folder:
            self.import_paths([folder])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def play_row(self, row):
        if not 0 <= row < len(self.paths):
            return
        self.activate_local()
        self.queue.reset(self.paths, row)
        self.queue_owner = self.library.active_id
        self.failed_paths.clear()
        if not self.start_track(row):
            self.step(1)

    def start_track(self, index, autoplay=True, position=0):
        if not 0 <= index < len(self.queue.paths):
            return False
        self.ensure_audio()
        path = self.queue.paths[index]
        if not Path(path).is_file():
            self.failed_paths.add(path)
            return False
        self.queue.index = index
        self.autoplay_requested = autoplay
        self.pending_seek = max(0, position)
        self.last_position = None
        source = QUrl.fromLocalFile(path)
        if self.player.source() == source and self.player.duration() > 0:
            self.pending_seek = None
            self.player.setPosition(max(0, position))
        else:
            self.player.setSource(source)
        if autoplay:
            self.player.play()
        if path in self.paths:
            self.list.setCurrentRow(self.paths.index(path))
        self.set_song_title(Path(path).stem)
        self.song_meta.setText('本地 MP3 · ' + MODES[self.queue.mode])
        self.status.setText(('正在播放：' if autoplay else '上次听到：') + Path(path).stem)
        self.save()
        return True

    def toggle(self):
        if self.playback_source == 'web':
            self.bilibili.toggle()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.autoplay_requested = False
            self.player.pause()
        elif self.player.source().isEmpty():
            row = self.list.currentRow()
            if row < 0:
                row = next((i for i in range(len(self.paths)) if not self.list.item(i).isHidden()), -1)
            self.play_row(row)
        else:
            self.autoplay_requested = True
            self.player.play()

    def step(self, direction):
        if self.playback_source == 'web':
            self.bilibili.step(direction)
            return
        if not self.queue.paths and self.paths:
            self.play_row(0)
            return
        for _ in range(len(self.queue.paths)):
            index = self.queue.advance(direction)
            if index is not None and self.queue.paths[index] not in self.failed_paths and self.start_track(index):
                return
        self.player.stop()
        self.autoplay_requested = False
        self.status.setText('歌单中没有可播放的文件，请检查歌曲位置或格式')

    def audio_error(self, *_):
        if self.playback_source == 'web':
            return
        path = self.current_path()
        self.failed_paths.add(path)
        self.status.setText('无法播放：' + Path(path).name)
        if self.autoplay_requested:
            QTimer.singleShot(0, lambda: self.step(1) if self.autoplay_requested and
                              self.current_path() == path else None)

    def position_changed(self, position):
        if self.playback_source == 'web' and self._player is not None and self.sender() is self._player:
            return
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        duration = self._player.duration() if self._player is not None else 0
        self.time.setText(f"{clock(position)} / {clock(duration)}")

    def state_changed(self, state):
        if self.playback_source == 'web':
            return
        self.last_position = None
        self.pet.playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText('暂停' if self.pet.playing else '播放')

    def media_changed(self, status):
        if self.playback_source == 'web':
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self.duration_changed(self.player.duration())
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            index = self.queue.advance(ended=True)
            if index is None:
                self.status.setText('这个歌单听完啦')
            elif not self.start_track(index):
                self.step(1)

    def save(self):
        self.settings.setValue('library_v1', self.library.dumps())
        self.settings.setValue('play_mode', self.queue.mode)
        self.settings.setValue('current_path', self.current_path())
        self.settings.setValue('current_position', self.pending_seek if self.pending_seek is not None
                               else self._player.position() if self._player is not None else 0)
        self.settings.setValue('current_queue', json.dumps(self.queue.paths, ensure_ascii=False))
        self.settings.setValue("volume", self.volume.value())
        self.settings.sync()

    def closeEvent(self, event):
        self.save()
        event.accept()


class Pet(DesktopPet):
    def __init__(self, data_dir=None, startup=None, settings=None, characters_dir=None):
        super().__init__(lambda owner: MusicPanel(owner, data_dir, startup, settings, characters_dir))


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setApplicationName("TianyiPet")
    app.setOrganizationName("TianyiPet")
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_dir / "instance.lock"))
    if not lock.tryLock(100):
        if '--autostart' not in sys.argv:
            QMessageBox.information(None, "天依桌宠", "桌宠已经在运行，请从系统托盘打开。")
        return 0
    app.setQuitOnLastWindowClosed(False)
    pet = Pet()
    app.aboutToQuit.connect(pet.panel.save)
    app.aboutToQuit.connect(pet.panel.bilibili.shutdown)
    app.aboutToQuit.connect(pet.panel.shutdown_audio)
    app.aboutToQuit.connect(pet.panel.store.close)
    app.aboutToQuit.connect(pet.close_live2d)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
