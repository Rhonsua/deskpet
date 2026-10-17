"""Transactional local statistics and pet progression, independent of Qt."""
import sqlite3
from datetime import datetime, timedelta

FOODS = {"小包子": (8, 15, 3, 3), "小笼包": (15, 30, 6, 6), "桂花糕": (12, 15, 10, 4)}


class PetStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS pet(id INTEGER PRIMARY KEY CHECK(id=1),
            level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0, notes INTEGER DEFAULT 20,
            hunger INTEGER DEFAULT 70, mood INTEGER DEFAULT 70,
            progress REAL DEFAULT 0, runtime REAL DEFAULT 0, last_feed TEXT);
          INSERT OR IGNORE INTO pet(id) VALUES(1);
          CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, seconds REAL DEFAULT 0,
            blocks INTEGER DEFAULT 0, bonus INTEGER DEFAULT 0, feeds INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS listening(day TEXT, path TEXT, seconds REAL DEFAULT 0,
            PRIMARY KEY(day,path));
          CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, at TEXT, reason TEXT,
            notes INTEGER, xp INTEGER);
        """)
        self.db.commit()

    def pet(self):
        return dict(self.db.execute("SELECT * FROM pet WHERE id=1").fetchone())

    def _grant(self, xp, notes, reason, now):
        pet = self.pet()
        level, value = pet['level'], pet['xp'] + xp
        while level < 30 and value >= 50 + 20 * (level - 1):
            value -= 50 + 20 * (level - 1)
            level += 1
        self.db.execute("UPDATE pet SET level=?,xp=?,notes=notes+? WHERE id=1",
                        (level, 0 if level == 30 else value, notes))
        self.db.execute("INSERT INTO ledger(at,reason,notes,xp) VALUES(?,?,?,?)",
                        (now.isoformat(), reason, notes, xp))

    def record(self, path, seconds, reward=True, end=None):
        if not 0 < seconds <= 5:
            return
        end = end or datetime.now()
        cursor = end - timedelta(seconds=seconds)
        with self.db:
            while cursor < end:
                midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
                stop = min(end, midnight)
                amount = (stop - cursor).total_seconds()
                day = cursor.date().isoformat()
                self.db.execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
                self.db.execute("UPDATE daily SET seconds=seconds+? WHERE day=?", (amount, day))
                self.db.execute("""INSERT INTO listening(day,path,seconds) VALUES(?,?,?)
                    ON CONFLICT(day,path) DO UPDATE SET seconds=seconds+excluded.seconds""", (day,path,amount))
                daily = self.db.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
                if reward and daily['blocks'] < 24:
                    progress = self.pet()['progress'] + amount
                    blocks = min(int(progress // 300), 24 - daily['blocks'])
                    self.db.execute("UPDATE pet SET progress=? WHERE id=1", (progress - blocks * 300,))
                    if blocks:
                        self.db.execute("UPDATE daily SET blocks=blocks+? WHERE day=?", (blocks, day))
                        self._grant(blocks * 5, blocks * 2, '听歌奖励', stop)
                        if not daily['bonus']:
                            self.db.execute("UPDATE daily SET bonus=1 WHERE day=?", (day,))
                            self._grant(10, 0, '每日首次听歌', stop)
                cursor = stop

    def tick_running(self, seconds):
        if not 0 < seconds <= 5:
            return
        with self.db:
            pet = self.pet()
            elapsed = pet['runtime'] + seconds
            steps = int(elapsed // 1800)
            mood = pet['mood']
            mood = max(70, mood - steps) if mood >= 70 else min(70, mood + steps)
            self.db.execute("UPDATE pet SET hunger=?,mood=?,runtime=? WHERE id=1",
                            (max(0, pet['hunger'] - steps * 5), mood, elapsed % 1800))

    def feed(self, food, now=None):
        now = now or datetime.now()
        if food not in FOODS:
            return False, '没有这种食物'
        with self.db:
            pet = self.pet()
            cost, hunger, mood, xp = FOODS[food]
            if pet['last_feed'] and (now - datetime.fromisoformat(pet['last_feed'])).total_seconds() < 10:
                return False, '稍等几秒，再喂一口吧'
            if pet['hunger'] >= 95:
                return False, '已经吃饱啦'
            if pet['notes'] < cost:
                return False, '音符不足，一起听歌攒一些吧'
            day = now.date().isoformat()
            self.db.execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
            feeds = self.db.execute("SELECT feeds FROM daily WHERE day=?", (day,)).fetchone()[0]
            earned = xp if feeds < 5 else 0
            self._grant(earned, -cost, '投喂：' + food, now)
            self.db.execute("UPDATE pet SET hunger=?,mood=?,last_feed=? WHERE id=1",
                            (min(100, pet['hunger'] + hunger), min(100, pet['mood'] + mood), now.isoformat()))
            self.db.execute("UPDATE daily SET feeds=feeds+1 WHERE day=?", (day,))
        return True, f'吃到{food}啦！经验 +{earned}'

    def stats(self, now=None):
        now = now or datetime.now()
        today = now.date().isoformat()
        week = (now.date() - timedelta(days=now.weekday())).isoformat()
        row = self.db.execute("SELECT seconds FROM daily WHERE day=?", (today,)).fetchone()
        weekly = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM daily WHERE day BETWEEN ? AND ?", (week,today)).fetchone()[0]
        total = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM daily").fetchone()[0]
        return {'today': row[0] if row else 0, 'week': weekly, 'total': total}

    def close(self):
        self.db.close()
