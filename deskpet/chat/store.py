"""Small separate database: complete conversation turns and editable character notes."""
import sqlite3


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
        rows = self.db.execute('SELECT role, content FROM messages WHERE character=? ORDER BY id DESC LIMIT ?',
                               (character, limit)).fetchall()
        return [dict(role=role, content=content) for role, content in reversed(rows)]

    def add_turn(self, character, user, assistant):
        with self.db:
            source = self.db.execute('INSERT INTO messages(character, role, content) VALUES (?, ?, ?)',
                                     (character, 'user', user)).lastrowid
            self.db.execute('INSERT INTO messages(character, role, content) VALUES (?, ?, ?)',
                            (character, 'assistant', assistant))
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
