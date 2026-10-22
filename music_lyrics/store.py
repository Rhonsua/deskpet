"""Local lyric cache and exact source bindings, without any network access."""
from datetime import datetime
from pathlib import Path
import re
import sqlite3

from .parser import parse, MAX_TEXT


def validate_source(key):
    if not isinstance(key, str) or len(key) > 4096:
        raise ValueError('请选择正在播放的本地、B站或网易云音源。')
    if key.startswith('local:') and Path(key[6:]).is_absolute():
        return key
    if re.fullmatch(r'netease:[1-9][0-9]{0,18}', key):
        return key
    match = re.fullmatch(r'bilibili:(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]*):([1-9][0-9]*)', key)
    if match and int(match[1]) <= 10000:
        return key
    raise ValueError('请选择准确本地路径、B站视频分P（1～10000）或网易云正整数歌曲ID。')


class LyricsStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=0.1)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS lyrics (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, song_id TEXT NOT NULL,
                    title TEXT NOT NULL, fetched_at TEXT NOT NULL, format TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(source,song_id));
                CREATE TABLE IF NOT EXISTS bindings (
                    source_key TEXT NOT NULL, lyric_id INTEGER NOT NULL REFERENCES lyrics(id),
                    offset_ms INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(source_key,lyric_id));
                CREATE TABLE IF NOT EXISTS selected (
                    source_key TEXT PRIMARY KEY, lyric_id INTEGER NOT NULL REFERENCES lyrics(id));
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def cache(self, source, song_id, title, body, format='lrc', now=None):
        if (source not in ('netease', 'file') or not isinstance(title, str) or len(title) > 500
                or not isinstance(song_id, str) or not song_id or len(song_id) > 4096):
            raise ValueError('歌词来源信息无效。')
        if source == 'netease' and not re.fullmatch(r'[0-9]{1,30}', song_id):
            raise ValueError('网易云歌曲 ID 无效。')
        if format not in ('lrc', 'srt'):
            raise ValueError('只支持 LRC 或 SRT。')
        parse(body, format)
        with self.db:
            self.db.execute('''INSERT INTO lyrics(source,song_id,title,fetched_at,format,body) VALUES (?,?,?,?,?,?)
                ON CONFLICT(source,song_id) DO UPDATE SET title=excluded.title,fetched_at=excluded.fetched_at,
                format=excluded.format,body=excluded.body''',
                (source, song_id, title, (now or datetime.now()).isoformat(), format, body))
        return self.db.execute('SELECT id FROM lyrics WHERE source=? AND song_id=?', (source, song_id)).fetchone()[0]

    def cached(self):
        return [dict(row) for row in self.db.execute(
            'SELECT id,source,song_id,title,fetched_at,format FROM lyrics ORDER BY fetched_at DESC,id DESC')]

    def cached_online(self, song_id):
        row = self.db.execute('SELECT * FROM lyrics WHERE source=? AND song_id=?',
                              ('netease', str(song_id))).fetchone()
        return dict(row) if row else None

    def get(self, lyric_id):
        row = self.db.execute('SELECT * FROM lyrics WHERE id=?', (lyric_id,)).fetchone()
        if row is None:
            raise ValueError('缓存歌词不存在。')
        return dict(row)

    def bind(self, source_key, lyric_id):
        validate_source(source_key)
        self.get(lyric_id)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO bindings(source_key,lyric_id) VALUES (?,?)', (source_key, lyric_id))
            self.db.execute('INSERT OR REPLACE INTO selected VALUES (?,?)', (source_key, lyric_id))

    def binding(self, source_key):
        row = self.db.execute('''SELECT l.*,b.offset_ms FROM selected s JOIN lyrics l ON l.id=s.lyric_id
            JOIN bindings b ON b.source_key=s.source_key AND b.lyric_id=s.lyric_id WHERE s.source_key=?''', (source_key,)).fetchone()
        return dict(row) if row else None

    def offset(self, source_key, offset_ms):
        if type(offset_ms) is not int or not -600000 <= offset_ms <= 600000:
            raise ValueError('偏移需要在提前/延后 600000 毫秒以内。')
        binding = self.binding(source_key)
        if binding is None:
            raise ValueError('当前音源还没有绑定歌词。')
        with self.db:
            self.db.execute('UPDATE bindings SET offset_ms=? WHERE source_key=? AND lyric_id=?',
                            (offset_ms, source_key, binding['id']))

    def unbind(self, source_key):
        with self.db:
            self.db.execute('DELETE FROM selected WHERE source_key=?', (source_key,))

    def settings(self):
        return dict(self.db.execute('SELECT key,value FROM settings').fetchall())

    def save_settings(self, values):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',
                                [(key, str(value)) for key, value in values.items()])


def read_lyric_file(path):
    path = Path(path)
    if path.suffix.lower() not in ('.lrc', '.srt'):
        raise ValueError('请选择 .lrc 或 .srt 文件。')
    with path.open('rb') as file:
        raw = file.read(MAX_TEXT * 4 + 1)
    if len(raw) > MAX_TEXT * 4:
        raise ValueError('歌词文件过大。')
    encodings = ('utf-16',) if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            parse(text, path.suffix[1:])
            return text
        except UnicodeError:
            continue
    raise ValueError('无法读取歌词文件编码，请转为 UTF-8。')
