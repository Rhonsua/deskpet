"""Small separate database: complete conversation turns and editable character notes."""
import sqlite3
import json


class ChatStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS profiles (
                character TEXT PRIMARY KEY, persona TEXT NOT NULL, memory TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, character TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS proactive_messages (
                id INTEGER PRIMARY KEY, character TEXT NOT NULL, content TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS messages_character ON messages(character, id);
        ''')
        columns = {row[1] for row in self.db.execute('PRAGMA table_info(messages)')}
        if 'stickers' not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN stickers TEXT NOT NULL DEFAULT '[]'")
        if 'parts' not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN parts TEXT NOT NULL DEFAULT '[]'")
        if 'sources' not in columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")
        self.db.commit()
        from .memory import MemoryBank
        self.memories = MemoryBank(self.db)

    def profile(self, character, default_persona):
        row = self.db.execute('SELECT persona, memory FROM profiles WHERE character=?', (character,)).fetchone()
        return row if row else (default_persona, '')

    def save_profile(self, character, persona, memory):
        if len(persona) > 8000 or len(memory) > 6000:
            raise ValueError('人设最多 8000 字符，记忆最多 6000 字符。')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO profiles VALUES (?, ?, ?)', (character, persona, memory))

    def history(self, character, limit=60):
        rows = self.db.execute('SELECT role, content, stickers, parts, sources FROM messages WHERE character=? ORDER BY id DESC LIMIT ?',
                               (character, limit)).fetchall()
        messages = []
        for role, content, encoded, encoded_parts, encoded_sources in reversed(rows):
            message = dict(role=role, content=content)
            try:
                keys = json.loads(encoded)
                if isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys):
                    message['stickers'] = keys[:4]
            except (ValueError, TypeError):
                pass
            try:
                parts = self.valid_parts(json.loads(encoded_parts))
                if parts and role == 'assistant':
                    message['parts'] = parts
            except (ValueError, TypeError):
                pass
            try:
                from .lookup_protocol import sources_from_rows
                sources = sources_from_rows(json.loads(encoded_sources))
                if sources and role == 'assistant':
                    message['sources'] = sources
            except (ValueError, TypeError):
                pass
            messages.append(message)
        return messages

    @staticmethod
    def valid_parts(parts):
        if not isinstance(parts, (list, tuple)):
            return []
        from .stickers import ID, MAX_PARTS
        result = []
        for part in parts[:MAX_PARTS]:
            if not isinstance(part, dict):
                continue
            if part.get('type') == 'text' and isinstance(part.get('text'), str) and part['text'].strip():
                result.append(dict(type='text', text=part['text']))
            elif part.get('type') == 'sticker' and isinstance(part.get('id'), str) and ID.fullmatch(part['id']):
                result.append(dict(type='sticker', id=part['id']))
        return result

    def add_turn(self, character, user, assistant, *, user_stickers=(), assistant_stickers=(), assistant_parts=(), sources=()):
        from .lookup_protocol import sources_from_rows
        with self.db:
            source = self.db.execute('INSERT INTO messages(character, role, content, stickers) VALUES (?, ?, ?, ?)',
                                     (character, 'user', user, json.dumps(list(user_stickers)[:1]))).lastrowid
            self.db.execute('INSERT INTO messages(character, role, content, stickers, parts, sources) VALUES (?, ?, ?, ?, ?, ?)',
                            (character, 'assistant', assistant, json.dumps(list(assistant_stickers)[:4]),
                             json.dumps(self.valid_parts(assistant_parts), ensure_ascii=False),
                             json.dumps(sources_from_rows(sources), ensure_ascii=False)))
            self.memories.capture(character, user, source)

    def clear_history(self, character):
        with self.db:
            # INTEGER PRIMARY KEY may reuse deleted message IDs. Retained
            # memories must not point to new messages after history is cleared.
            self.db.execute('UPDATE companion_memories SET source_id=0 WHERE character=?', (character,))
            self.db.execute('DELETE FROM messages WHERE character=?', (character,))
            self.db.execute('DELETE FROM proactive_messages WHERE character=?', (character,))

    def add_proactive(self, character, text):
        with self.db:
            self.db.execute('INSERT INTO proactive_messages(character,content) VALUES (?,?)',
                            (character, text))

    def last_proactive(self, character):
        rows = self.db.execute('SELECT content FROM proactive_messages WHERE character=? ORDER BY id DESC LIMIT 3',
                               (character,)).fetchall()
        return '；'.join(row[0] for row in reversed(rows))

    def close(self):
        self.db.close()
