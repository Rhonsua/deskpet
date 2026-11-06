"""Small local memories grounded in user words; no model calls or embeddings."""
import hashlib
import json
import re
import unicodedata
from contextlib import nullcontext
from datetime import datetime, timezone

MAX_RECORDS = 200
CONTEXT_LIMIT = 1800


def local_time(created):
    return datetime.fromisoformat(created).replace(tzinfo=timezone.utc).astimezone().isoformat(timespec='minutes')


def normal(text):
    return unicodedata.normalize('NFKC', text).strip(' \n\t。！!').casefold()


def remember_request(text):
    match = re.fullmatch(r'(?:请|帮我)?(?:记住|记一下|记下来)[：:,，\s]*(.{1,300})', text.strip())
    return match[1].strip() if match else None


def eligible(text):
    if not 2 <= len(text) <= 400:
        return False
    # Do not promote secrets, commands, quoted roleplay or technical tasks to
    # reusable memories. The original conversation remains in chat history.
    if re.search(r'密码|口令|验证码|密钥|身份证|银行卡|电话|手机号|住址|api[ _-]?key|token|'
                 r'https?://|[a-z]:[\\/]|\d{7,}|[\w.+-]+@[\w.-]+|'
                 r'系统提示|忽略.{0,8}(?:规则|指令|限制)|执行命令|扮演|假装|如果|假如|'
                 r'开玩笑|骗你|他说|她说|也许|可能|大概|好像|吗$|[“”「」`\[\]{}]|[?？]', text, re.I):
        return False
    from .scope import request_refusal
    return request_refusal(text) is None


def extract(text):
    """One exact declaration becomes a fact; other first-person words stay dated notes."""
    explicit = remember_request(text)
    value = (explicit if explicit is not None else text).strip(' \n\t。！!')
    if not eligible(value):
        return None
    name = re.fullmatch(r'(?:以后)?(?:请)?(?:叫我|称呼我为|我叫|我的名字是)([^，,。；;\n]{1,24})', value)
    if name:
        return 'name', 'fact', value
    preference = re.fullmatch(r'我(?:一直|平时|很|比较|最|现在|以后)?'
                              r'(不再喜欢|不喜欢|喜欢|讨厌|爱)([^，,。；;\n]{1,60}?)(?:了)?', value)
    if preference and not re.search(r'但是|不过|只是|除非|的时候|不代表', value):
        subject = normal(preference[2])
        return 'preference:' + subject, 'fact', value
    diet = re.fullmatch(r'我(?:一直|平时|现在|以后)?(?:不再吃|不吃|不能吃|能吃|吃)([^，,。；;\n]{1,40}?)(?:了)?', value)
    if diet:
        return 'diet:' + normal(diet[1]), 'fact', value
    if explicit is not None or (len(value) >= 8 and re.match(r'我(?:今天|昨天|最近|这周|上周|下周|明天|刚|正在|准备|打算|终于|和|的|在)', value)):
        return 'note:' + hashlib.sha256(normal(value).encode()).hexdigest(), 'note', value
    return None


def keywords(text):
    text = normal(text)
    text = re.sub(r'还记得|记不记得|记得|上次|之前|后来|现在|今天|昨天|最近|那个|这个|什么|怎么样|喜欢|不喜欢|我|你|天依', ' ', text)
    words = set(re.findall(r'[a-z0-9_]{2,}', text))
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(run[i:i+2] for i in range(len(run) - 1))
    return words


class MemoryBank:
    def __init__(self, db):
        self.db = db
        db.executescript('''
            CREATE TABLE IF NOT EXISTS companion_memory_options (
                character TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS companion_memories (
                id INTEGER PRIMARY KEY, character TEXT NOT NULL, slot TEXT NOT NULL,
                kind TEXT NOT NULL, content TEXT NOT NULL, source_id INTEGER NOT NULL,
                created TEXT NOT NULL, UNIQUE(character, slot));
            CREATE INDEX IF NOT EXISTS companion_memory_character ON companion_memories(character, id);
        ''')

    def _ensure(self, character):
        row = self.db.execute('SELECT enabled FROM companion_memory_options WHERE character=?', (character,)).fetchone()
        if row is not None:
            return bool(row[0])
        # Import bounded, literal user statements from existing conversations once.
        # Deleting memories never re-imports them on the next startup.
        with (nullcontext() if self.db.in_transaction else self.db):
            self.db.execute('INSERT INTO companion_memory_options VALUES (?,1)', (character,))
            rows = self.db.execute("SELECT id, content, created FROM messages WHERE character=? AND role='user' ORDER BY id DESC LIMIT 200", (character,)).fetchall()
            for source, text, created in reversed(rows):
                self._capture(character, text, source, created)
        return True

    def enabled(self, character):
        return self._ensure(character)

    def set_enabled(self, character, enabled):
        with self.db:
            self.db.execute('INSERT INTO companion_memory_options VALUES (?,?) ON CONFLICT(character) DO UPDATE SET enabled=excluded.enabled', (character, int(bool(enabled))))

    def _capture(self, character, text, source_id, created):
        result = extract(text)
        if result is None:
            return
        slot, kind, content = result
        self.db.execute('''INSERT INTO companion_memories(character,slot,kind,content,source_id,created)
            VALUES (?,?,?,?,?,?) ON CONFLICT(character,slot) DO UPDATE SET
            content=excluded.content, source_id=excluded.source_id, created=excluded.created''',
            (character, slot, kind, content, source_id, created))
        self.db.execute('''DELETE FROM companion_memories WHERE character=? AND id NOT IN
            (SELECT id FROM companion_memories WHERE character=? ORDER BY source_id DESC,created DESC,id DESC LIMIT ?)''',
            (character, character, MAX_RECORDS))

    def capture(self, character, user, source_id):
        # Called inside ChatStore's successful-turn transaction. No commits here.
        if self._ensure(character):
            created = self.db.execute('SELECT created FROM messages WHERE id=?', (source_id,)).fetchone()[0]
            self._capture(character, user, source_id, created)

    def records(self, character):
        self._ensure(character)
        rows = self.db.execute('''SELECT id,kind,content,created,slot,source_id FROM companion_memories
            WHERE character=? ORDER BY source_id DESC,created DESC,id DESC LIMIT ?''', (character, MAX_RECORDS)).fetchall()
        return [dict(zip(('id', 'kind', 'content', 'created', 'slot', 'source_id'), row)) for row in rows]

    def delete(self, character, ids):
        self._ensure(character)
        with self.db:
            self.db.executemany('DELETE FROM companion_memories WHERE character=? AND id=?',
                                ((character, int(item)) for item in ids))

    def clear(self, character):
        self._ensure(character)
        with self.db:
            self.db.execute('DELETE FROM companion_memories WHERE character=?', (character,))

    def recall(self, character, query, proactive=False):
        if not self.enabled(character):
            return ''
        rows = self.records(character)
        terms = keywords(query)
        recent = {r[0] for r in self.db.execute('SELECT id FROM messages WHERE character=? ORDER BY id DESC LIMIT 12', (character,))}
        scored = [(len(terms & keywords(row['content'])), row) for row in rows]
        facts = sorted(((score, row) for score, row in scored if row['kind'] == 'fact'),
                       key=lambda item: (item[1]['slot'] == 'name', item[0], item[1]['source_id']), reverse=True)
        notes = sorted(((score, row) for score, row in scored if row['kind'] == 'note'
                        and row['source_id'] not in recent and score > 0),
                       key=lambda item: (item[0], item[1]['source_id']), reverse=True)
        # Proactive chat gets a small number of actual recent experiences, never
        # the pseudo-user proactive prompt as a search query or a memory source.
        if proactive:
            notes = [(0, row) for row in rows if row['kind'] == 'note' and row['source_id'] not in recent
                     and self.db.execute("SELECT julianday('now')-julianday(?) <= 7", (row['created'],)).fetchone()[0]][:2]
        selected = [row for _, row in facts[:6]] + [row for _, row in notes[:2]]
        result = []
        for row in selected:
            # SQLite stores UTC; include the current local offset so "today" in
            # an old quote isn't anchored to the UTC calendar date by mistake.
            value = json.dumps({'类型': '明确偏好或称呼' if row['kind'] == 'fact' else '旧话题',
                                '记录时间': local_time(row['created']), '用户原话': row['content']}, ensure_ascii=False)
            if sum(map(len, result)) + len(value) + len(result) > CONTEXT_LIMIT:
                continue
            result.append(value)
        return '\n'.join(result)
