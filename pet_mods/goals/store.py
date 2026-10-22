"""Transactional, local-time goal storage; deliberately independent of characters."""
from collections import defaultdict, deque
from datetime import datetime, timedelta
import sqlite3


def timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ValueError('日期需要本地时间。')
    return value.isoformat(timespec='microseconds')


def validate(title, deadline, steps, stagnation_days, notes=''):
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError('目标名称需要 1～120 个字符。')
    timestamp(deadline)
    if (not isinstance(steps, (list, tuple)) or len(steps) > 50
            or any(not isinstance(step, str) or not step.strip() or len(step) > 200 for step in steps)):
        raise ValueError('待办最多 50 条，每条需要 1～200 个字符。')
    if type(stagnation_days) is not int or not 1 <= stagnation_days <= 30:
        raise ValueError('停滞提醒间隔需要 1～30 天。')
    if not isinstance(notes, str) or len(notes) > 4000:
        raise ValueError('备注最多 4000 个字符。')
    return title.strip(), [step.strip() for step in steps]


class GoalStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=0.1)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    deadline TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_progress TEXT,
                    resumed_at TEXT NOT NULL,
                    snoozed_until TEXT,
                    last_reminded TEXT,
                    stagnation_days INTEGER NOT NULL DEFAULT 2,
                    notes TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS steps (
                    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    done INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(goal_id, position)
                );
            ''')
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def get(self, goal_id):
        row = self.db.execute('SELECT * FROM goals WHERE id=?', (goal_id,)).fetchone()
        if row is None:
            raise ValueError('目标不存在，可能已经删除。')
        goal = dict(row)
        for key in ('deadline', 'created_at', 'last_progress', 'resumed_at', 'snoozed_until', 'last_reminded'):
            goal[key] = datetime.fromisoformat(goal[key]) if goal[key] else None
        goal['steps'] = [dict(text=item['text'], done=bool(item['done'])) for item in self.db.execute(
            'SELECT text, done FROM steps WHERE goal_id=? ORDER BY position', (goal_id,))]
        return goal

    def list_goals(self):
        return [self.get(row[0]) for row in self.db.execute(
            "SELECT id FROM goals ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, deadline, id")]

    def create(self, title, deadline, steps=(), stagnation_days=2, now=None, notes=''):
        title, steps = validate(title, deadline, steps, stagnation_days, notes)
        stamp = timestamp(now or datetime.now())
        with self.db:
            cursor = self.db.execute('''INSERT INTO goals
                (title,deadline,created_at,last_progress,resumed_at,stagnation_days,notes)
                VALUES (?,?,?,?,?,?,?)''', (title, timestamp(deadline), stamp, None, stamp, stagnation_days, notes))
            goal_id = cursor.lastrowid
            self.db.executemany('INSERT INTO steps(goal_id,position,text) VALUES (?,?,?)',
                                [(goal_id, index, text) for index, text in enumerate(steps)])
        return goal_id

    def update(self, goal_id, title, deadline, steps, stagnation_days=2, now=None, notes=''):
        title, steps = validate(title, deadline, steps, stagnation_days, notes)
        old = self.get(goal_id)
        retained = defaultdict(deque)
        for step in old['steps']:
            retained[step['text']].append(step['done'])
        rows = []
        for index, text in enumerate(steps):
            done = retained[text].popleft() if retained[text] else False
            rows.append((goal_id, index, text, int(done)))
        # Editing metadata or rewriting a step is not evidence of progress.
        with self.db:
            self.db.execute('UPDATE goals SET title=?,deadline=?,stagnation_days=?,notes=? WHERE id=?',
                            (title, timestamp(deadline), stagnation_days, notes, goal_id))
            self.db.execute('DELETE FROM steps WHERE goal_id=?', (goal_id,))
            self.db.executemany('INSERT INTO steps VALUES (?,?,?,?)', rows)

    def set_step_done(self, goal_id, position, done, now=None):
        if type(done) is not bool:
            raise ValueError('待办完成状态无效。')
        goal = self.get(goal_id)
        if type(position) is not int or not 0 <= position < len(goal['steps']):
            raise ValueError('待办不存在。')
        if goal['steps'][position]['done'] == done:
            return
        with self.db:
            self.db.execute('UPDATE steps SET done=? WHERE goal_id=? AND position=?',
                            (int(done), goal_id, position))
            if done:
                self.db.execute('UPDATE goals SET last_progress=? WHERE id=?',
                                (timestamp(now or datetime.now()), goal_id))

    def record_progress(self, goal_id, now=None):
        self.get(goal_id)
        with self.db:
            self.db.execute('UPDATE goals SET last_progress=? WHERE id=?',
                            (timestamp(now or datetime.now()), goal_id))

    def set_status(self, goal_id, status, now=None):
        if status not in ('active', 'paused', 'completed'):
            raise ValueError('目标状态无效。')
        goal = self.get(goal_id)
        with self.db:
            if status == 'active' and goal['status'] != 'active':
                # Resuming resets stagnation, not the factual progress record or cooldown.
                self.db.execute('UPDATE goals SET status=?,resumed_at=? WHERE id=?',
                                (status, timestamp(now or datetime.now()), goal_id))
            else:
                self.db.execute('UPDATE goals SET status=? WHERE id=?', (status, goal_id))

    def snooze(self, goal_id, now=None, hours=1):
        if type(hours) not in (int, float) or not 0 < hours <= 24 * 30:
            raise ValueError('稍后提醒时长无效。')
        self.get(goal_id)
        with self.db:
            self.db.execute('UPDATE goals SET snoozed_until=? WHERE id=?',
                            (timestamp((now or datetime.now()) + timedelta(hours=hours)), goal_id))

    def mark_reminded(self, goal_id, now):
        with self.db:
            self.db.execute('UPDATE goals SET last_reminded=? WHERE id=?', (timestamp(now), goal_id))

    def delete(self, goal_id):
        self.get(goal_id)
        with self.db:
            self.db.execute('DELETE FROM goals WHERE id=?', (goal_id,))
