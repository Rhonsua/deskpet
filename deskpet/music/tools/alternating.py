"""Alternate local and Bilibili tracks without changing either queue's mode."""
import json
from pathlib import Path


class AlternatingPlayback:
    def __init__(self, panel):
        self.panel = panel
        self.enabled = panel.settings.value('music/alternate_sources', False, type=bool)
        try:
            positions = json.loads(panel.settings.value('music/alternate_positions', '{}'))
        except (ValueError, TypeError):
            positions = {}
        self.positions = positions if isinstance(positions, dict) else {}
        self.history = []
        self.history_index = -1
        self.revisiting = False

    def remember(self, source, key):
        owner = (self.panel.queue_owner or self.panel.library.active_id) if source == 'local' else ''
        entry = (source, owner, key)
        self.positions[source] = [owner, key]
        self.panel.settings.setValue('music/alternate_positions',
                                     json.dumps(self.positions, ensure_ascii=False))
        if self.enabled and not self.revisiting:
            if self.history_index < 0 or self.history[self.history_index] != entry:
                self.history = (self.history[:self.history_index + 1] + [entry])[-100:]
                self.history_index = len(self.history) - 1

    def advance(self, source, direction=1):
        if not self.enabled or source not in ('local', 'web'):
            return False
        if direction < 0 or self.history_index < len(self.history) - 1:
            index = self.history_index + direction
            while 0 <= index < len(self.history):
                previous_source, owner, key = self.history[index]
                if previous_source == 'local' and owner != self.panel.library.active_id:
                    index += direction
                    continue
                self.revisiting = True
                try:
                    if self._play(previous_source, key):
                        self.history_index = index
                        return True
                finally:
                    self.revisiting = False
                index += direction
        # Empty/missing local files do not block the available source.
        other = 'web' if source == 'local' else 'local'
        for target in (other, source):
            keys = self._keys(target)
            queue = self.panel.bilibili.queue if target == 'web' else self.panel.queue
            if queue.reverse and queue.mode != 'shuffle':
                keys.reverse()
            if not keys:
                continue
            owner = self.panel.library.active_id if target == 'local' else ''
            previous = self.positions.get(target)
            index = (-1 if direction > 0 else 0)
            if isinstance(previous, list) and len(previous) == 2 and previous[0] == owner and previous[1] in keys:
                index = keys.index(previous[1])
            if self._play(target, keys[(index + direction) % len(keys)]):
                return True
        return False

    def _keys(self, source):
        if source == 'web':
            return [t['url'] for t in self.panel.bilibili.tracks]
        return [p for p in self.panel.paths
                if Path(p).is_file() and p not in self.panel.failed_paths]

    def _play(self, source, key):
        if key not in self._keys(source):
            return False
        p = self.panel
        if source == 'web':
            keys = [t['url'] for t in p.bilibili.tracks]
            p.bilibili.play_row(keys.index(key))
            return True
        p.activate_local()
        p.queue.reset(p.paths, p.paths.index(key))
        p.queue_owner = p.library.active_id
        return p.start_track(p.queue.index)
