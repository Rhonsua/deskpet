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
            CREATE INDEX IF NOT EXISTS messages_character ON messages(character, id);
        ''')

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
            self.db.executemany('INSERT INTO messages(character, role, content) VALUES (?, ?, ?)',
                                [(character, 'user', user), (character, 'assistant', assistant)])

    def clear_history(self, character):
        with self.db:
            self.db.execute('DELETE FROM messages WHERE character=?', (character,))

    def close(self):
        self.db.close()
