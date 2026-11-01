"""Lyric binding and real-playback-clock synchronization; no independent clock."""
from pathlib import Path
import sqlite3
import re

from PySide6.QtCore import QObject, Signal, QEvent

from .parser import parse
from .store import LyricsStore, read_lyric_file, validate_source


class LyricsController(QObject):
    changed = Signal()
    bound = Signal(str, str)

    def __init__(self, pet, data_dir, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.source_key = ''
        self.position_ms = 0
        self.duration_ms = 0
        self.playing = False
        self.valid = False
        self.document = None
        self.binding = None
        self.status = '播放本地歌曲或 B站视频后，可为准确音源绑定歌词。'
        self.store = None
        self.overlay = None
        self.closed = False
        self.settings = dict(enabled=True, font_size=18, position='below', x_offset=0, y_offset=8,
                             color='#ffffff', left_passthrough=True)
        try:
            root = Path(data_dir) / 'lyrics'
            root.mkdir(parents=True, exist_ok=True)
            self.store = LyricsStore(root / 'lyrics.db')
            saved = self.store.settings()
            color = saved.get('color', '#ffffff')
            self.settings.update(color=color.lower() if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else '#ffffff',
                                 left_passthrough=saved.get('left_passthrough', 'True') == 'True')
            self.settings.update(enabled=saved.get('enabled', 'True') == 'True',
                                 font_size=max(10, min(48, int(saved.get('font_size', 18)))),
                                 position='above' if saved.get('position') == 'above' else 'below',
                                 x_offset=max(-2000, min(2000, int(saved.get('x_offset', 0)))),
                                 y_offset=max(-2000, min(2000, int(saved.get('y_offset', 8)))))
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status = '歌词存储暂不可用：' + str(error)
        self.pet.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.pet:
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self._hide()
            elif event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
                                  QEvent.Type.WindowStateChange):
                self._render()
        return super().eventFilter(watched, event)

    def _store(self):
        if self.closed or self.store is None:
            raise ValueError('歌词存储不可用，请重启桌宠后重试。')
        return self.store

    def cache_online(self, song_id, title, lrc):
        lyric_id = self._store().cache('netease', str(song_id), title, lrc)
        self.status = '已缓存歌词；请确认当前音源与歌曲版本后再绑定。'
        self.changed.emit()
        return lyric_id

    def get_cached(self, song_id=None):
        """No argument: metadata list. Song ID: full cached record including body, or None."""
        return self._store().cached() if song_id is None else self._store().cached_online(song_id)

    def import_online(self, song_id, title, lrc, source_key):
        validate_source(source_key)
        lyric_id = self.cache_online(song_id, title, lrc)
        self.bind_cached(lyric_id, source_key)
        return lyric_id

    def bind_cached(self, lyric_id, source_key=None):
        source_key = self.source_key if source_key is None else source_key
        self._store().bind(source_key, lyric_id)
        cached = self._store().get(lyric_id)
        if source_key == self.source_key:
            self._load_source(auto_match=False)
            self._render()
        self.status = '已按准确音源绑定歌词。翻唱、Live 和剪辑版请自行校准。'
        if self.document is not None and not self.document.timed and self.document.plain_text:
            self.status += ' 当前为纯文本，没有可同步时间轴，仅供预览。'
        self.changed.emit()
        if cached['source'] == 'netease':
            self.bound.emit(cached['song_id'], source_key)

    def import_file(self, path, source_key=None):
        source_key = self.source_key if source_key is None else source_key
        validate_source(source_key)
        path = Path(path).resolve()
        body = read_lyric_file(path)
        lyric_id = self._store().cache('file', str(path), path.stem, body, path.suffix[1:].lower())
        self.bind_cached(lyric_id, source_key)
        return lyric_id

    def set_offset(self, offset_ms):
        self._store().offset(self.source_key, offset_ms)
        if self.binding:
            self.binding['offset_ms'] = offset_ms
        self._render()
        self.status = '偏移已保存到当前音源与这份歌词的绑定；正值提前，负值延后。'
        self.changed.emit()

    def unbind(self):
        self._store().unbind(self.source_key)
        self.binding = self.document = None
        self._hide()
        self.status = '已解除绑定；重新切入本地歌曲时仍会尝试同名 LRC。'
        self.changed.emit()

    def configure(self, **values):
        settings = dict(self.settings, **values)
        if (set(settings) != set(self.settings) or type(settings['enabled']) is not bool
                or type(settings['left_passthrough']) is not bool
                or not isinstance(settings['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', settings['color'])
                or type(settings['font_size']) is not int or not 10 <= settings['font_size'] <= 48
                or settings['position'] not in ('below', 'above')
                or any(type(settings[key]) is not int or not -2000 <= settings[key] <= 2000
                       for key in ('x_offset', 'y_offset'))):
            raise ValueError('字幕设置无效。')
        settings['color'] = settings['color'].lower()
        self._store().save_settings(settings)
        self.settings = settings
        self._render()
        self.changed.emit()

    def _overlay_settings(self, values):
        try:
            self.configure(**values)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.status = '歌词设置未保存，请重试：' + str(error)
            self.changed.emit()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.overlay, '歌词设置', self.status)

    def _load_source(self, auto_match=True):
        self.document = self.binding = None
        self._hide()
        if not self.source_key:
            self.status = '当前没有可同步的音源。'
            return
        validate_source(self.source_key)
        binding = self._store().binding(self.source_key)
        if binding is None and auto_match and self.source_key.startswith('local:'):
            audio = Path(self.source_key[6:])
            if audio.suffix.lower() == '.mp3':
                lyric = audio.with_suffix('.lrc')
                if lyric.is_file():
                    body = read_lyric_file(lyric)
                    lyric_id = self._store().cache('file', str(lyric.resolve()), lyric.stem, body)
                    self._store().bind(self.source_key, lyric_id)
                    binding = self._store().binding(self.source_key)
        self.binding = binding
        if binding:
            self.document = parse(binding['body'], binding['format'])
            if self.document.timed:
                self.status = '已绑定：' + binding['title']
            elif self.document.plain_text:
                self.status = '已载入纯文本歌词；没有时间轴，仅供预览，不显示同步字幕。'
            else:
                self.status = '这份来源没有可显示歌词；可能是纯音乐，或尚未提供歌词。'
        else:
            self.status = '当前音源没有歌词；可导入 LRC/SRT 或明确绑定云端缓存。'

    def update(self, source_key, position_ms, playing, duration_ms=0, valid=True):
        if self.closed:
            return
        changed = source_key != self.source_key
        self.source_key = source_key
        self.position_ms = max(0, int(position_ms))
        self.duration_ms = max(0, int(duration_ms))
        self.playing = bool(playing)
        self.valid = bool(valid)
        if changed:
            try:
                self._load_source()
            except (ValueError, OSError, sqlite3.Error) as error:
                self.document = self.binding = None
                self.status = '歌词载入失败，不影响播放：' + str(error)
            self.changed.emit()
        self._render()

    def _hide(self):
        if self.overlay is not None:
            self.overlay.text = ''
            self.overlay.hide()

    def _render(self):
        if (self.closed or not self.valid or not self.settings['enabled'] or not self.source_key or not self.document
                or not self.document.timed or not self.pet.isVisible() or self.pet.isMinimized()
                or (self.duration_ms > 0 and self.position_ms >= self.duration_ms)):
            self._hide()
            return
        text = self.document.at(self.position_ms + self.binding['offset_ms'])
        if not text:
            self._hide()
            return
        if self.overlay is None:
            from .overlay import LyricsOverlay
            self.overlay = LyricsOverlay()
            self.overlay.settingsRequested.connect(self._overlay_settings)
        screen = self.pet.screen()
        if screen is None:
            self._hide()
            return
        rect = screen.availableGeometry()
        pet_rect = self.pet.frameGeometry()
        width = min(580, max(80, rect.width() - 16))
        self.overlay.set_content(text, self.settings['font_size'], width)
        self.overlay.set_options(self.settings['color'], self.settings['left_passthrough'])
        x = pet_rect.center().x() - width // 2 + self.settings['x_offset']
        if self.settings['position'] == 'above':
            y = pet_rect.top() - self.overlay.height() - self.settings['y_offset']
        else:
            y = pet_rect.bottom() + 1 + self.settings['y_offset']
        # Stay anchored to the pet, including at screen edges. Clamping the
        # subtitle separately makes it stop following while the pet keeps moving.
        self.overlay.move(x, y)
        if not self.overlay.isVisible():
            self.overlay.show()

    def create_widget(self, parent=None):
        from .widget import LyricsWidget
        return LyricsWidget(self, parent)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.pet.removeEventFilter(self)
        self._hide()
        if self.overlay is not None:
            self.overlay.close()
            self.overlay.deleteLater()
        if self.store is not None:
            self.store.close()
            self.store = None
