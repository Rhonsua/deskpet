"""Atomic playlist snapshots and optimistic writes to the shared settings store."""
import json
from pathlib import Path
from PySide6.QtCore import QSaveFile, QIODevice, QSettings
from .library import MusicLibrary


def valid_payload(raw):
    try:
        data = json.loads(raw)
        lists = data['playlists']
        if not isinstance(lists, list) or not lists:
            return False
        ids = []
        for item in lists:
            if (not isinstance(item, dict) or not isinstance(item.get('name'), str)
                    or not isinstance(item.get('id'), str) or not item['id']
                    or not isinstance(item.get('paths'), list)
                    or any(not isinstance(p, str) for p in item['paths'])):
                return False
            ids.append(item['id'])
        return len(set(ids)) == len(ids) and data.get('active_id') in ids
    except (ValueError, TypeError, KeyError):
        return False


def write_atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = QSaveFile(str(path))
    if not f.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(f.errorString())
    data = raw.encode('utf8')
    if f.write(data) != len(data):
        f.cancelWriting()
        raise OSError('歌单备份写入不完整')
    if not f.commit():
        raise OSError(f.errorString())


class LibraryStorage:
    def __init__(self, settings, data_dir):
        self.settings = settings
        self.path = Path(data_dir) / 'music-library.json'
        self.backup = Path(data_dir) / 'music-library.backup.json'
        self.expected = settings.value('library_v1', '')
        self.blocked = False
        self.notice = ''

    def load(self, legacy=()):
        raw = self.expected
        if valid_payload(raw):
            library = MusicLibrary(raw)
            try:
                self._snapshot(library.dumps())
            except (OSError, UnicodeError):
                self.notice = '歌单已读取，但本机备份暂时无法写入；请检查数据目录空间或权限。'
            return library
        for path in (self.path, self.backup):
            try:
                saved = path.read_text('utf8')
            except (OSError, UnicodeError):
                continue
            if valid_payload(saved):
                self.notice = '歌单配置无法读取，已从本机备份恢复。'
                return MusicLibrary(saved)
        self.blocked = bool(raw)
        if self.blocked:
            self.notice = '歌单配置无法读取，已保留原记录，暂停自动保存歌单。'
        return MusicLibrary('', legacy)

    def _snapshot(self, raw):
        try:
            previous = self.path.read_text('utf8') if self.path.exists() else ''
        except UnicodeError:
            previous = ''  # Keep the separate valid backup when this file is damaged.
        if previous == raw:
            return
        # One older nonempty snapshot survives even an intentional clear.
        if valid_payload(previous) and any(x['paths'] for x in json.loads(previous)['playlists']):
            write_atomic(self.backup, previous)
        elif not self.backup.exists() and any(x['paths'] for x in json.loads(raw)['playlists']):
            write_atomic(self.backup, raw)
        write_atomic(self.path, raw)

    def save(self, library):
        if self.blocked:
            raise ValueError(self.notice)
        raw = library.dumps()
        self.settings.sync()
        current = self.settings.value('library_v1', '')
        if current != self.expected and current != raw:
            raise ValueError('歌单已被另一个窗口或程序修改，为避免覆盖，已停止保存；请重新打开桌宠。')
        self._snapshot(raw)
        if current != raw:
            self.settings.setValue('library_v1', raw)
            self.settings.sync()
            if self.settings.status() != QSettings.Status.NoError:
                raise OSError('歌单配置未能保存，已保留本机备份；请检查数据目录或设置权限。')
        self.expected = raw
