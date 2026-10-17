"""Playlist persistence and playback order, independent of the UI and audio driver."""
import json
import os
import random
import uuid
from pathlib import Path


MODES = {'order': '顺序播放', 'loop': '列表循环', 'single': '单曲循环', 'shuffle': '随机播放'}


def normalized(paths):
    result, seen = [], set()
    for item in paths:
        if not isinstance(item, str) or not item.strip():
            continue
        path = str(Path(item).resolve())
        key = os.path.normcase(path)
        if Path(path).suffix.lower() == '.mp3' and key not in seen:
            result.append(path)
            seen.add(key)
    return result


class MusicLibrary:
    def __init__(self, payload='', legacy_paths=()):
        self.playlists = []
        self.active_id = ''
        try:
            data = json.loads(payload)
            for item in data.get('playlists', []):
                if isinstance(item, dict) and isinstance(item.get('name'), str):
                    self.playlists.append({'id': str(item.get('id') or uuid.uuid4().hex),
                                           'name': item['name'][:40] or '我的歌单',
                                           'paths': normalized(item.get('paths', []))})
            self.active_id = data.get('active_id', '')
        except (ValueError, TypeError, AttributeError):
            self.playlists = []
        if not self.playlists:
            self.create('我的歌单')
            self.active['paths'] = normalized(legacy_paths)
        if not any(p['id'] == self.active_id for p in self.playlists):
            self.active_id = self.playlists[0]['id']

    @property
    def active(self):
        return next(p for p in self.playlists if p['id'] == self.active_id)

    @property
    def paths(self):
        return self.active['paths']

    def create(self, name):
        name = name.strip()[:40]
        if not name:
            raise ValueError('歌单名称不能为空')
        item = {'id': uuid.uuid4().hex, 'name': name, 'paths': []}
        self.playlists.append(item)
        self.active_id = item['id']
        return item['id']

    def rename(self, name):
        name = name.strip()[:40]
        if not name:
            raise ValueError('歌单名称不能为空')
        self.active['name'] = name

    def delete(self):
        if len(self.playlists) <= 1:
            raise ValueError('至少保留一个歌单')
        self.playlists.remove(self.active)
        self.active_id = self.playlists[0]['id']

    def add(self, paths):
        before = len(self.paths)
        self.active['paths'] = normalized(self.paths + list(paths))
        return len(self.paths) - before

    def remove(self, indices):
        indices = set(indices)
        self.active['paths'] = [p for i, p in enumerate(self.paths) if i not in indices]

    def dumps(self):
        return json.dumps({'version': 1, 'active_id': self.active_id, 'playlists': self.playlists}, ensure_ascii=False)


class PlaybackQueue:
    def __init__(self, mode='order'):
        self.mode = mode if mode in MODES else 'order'
        self.paths = []
        self.index = -1
        self.bag = []
        self.history = []

    def reset(self, paths, index):
        self.paths = list(paths)
        self.index = index if 0 <= index < len(self.paths) else -1
        self.bag = []
        self.history = []

    def advance(self, direction=1, ended=False):
        if not self.paths:
            return None
        if ended and self.mode == 'single' and self.index >= 0:
            return self.index
        if self.mode == 'shuffle':
            if direction < 0 and self.history:
                self.index = self.history.pop()
                return self.index
            if not self.bag:
                self.bag = [i for i in range(len(self.paths)) if i != self.index]
                random.shuffle(self.bag)
            if self.bag:
                if self.index >= 0:
                    self.history.append(self.index)
                self.index = self.bag.pop()
            else:
                self.index = max(0, self.index)
            return self.index
        next_index = self.index + direction
        if ended and self.mode == 'order' and next_index >= len(self.paths):
            return None
        self.index = next_index % len(self.paths)
        return self.index
