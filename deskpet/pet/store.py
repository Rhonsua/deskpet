"""Transactional local statistics and pet progression, independent of Qt."""
import sqlite3
from datetime import datetime, timedelta

from .catalog import AUTO_FULLNESS, AUTO_MEAL, DEFAULT_BACKGROUND, FOOD_BY_NAME, FOODS, ITEMS

# Outside the public Mod ID namespace. Ownership can use the existing purchase ledger.
SHOP_OWNER = '@desktop'
REWARD_SECONDS = 300
DAILY_REWARD_BLOCKS = 50
BOOST_BLOCKS = 12
BOOST_NOTES = 6
STANDARD_NOTES = 2
DAILY_NOTE_LIMIT = 100
DAILY_INTERACTIONS = {'headpat': ('摸摸头', 6), 'chat': ('陪伴对话', 6), 'game': ('节奏演出或猜歌', 10)}
COMPANY_STEP = 600
COMPANY_NOTES = 4
COMPANY_STEPS = 3
DAILY_COMPANION_LIMIT = sum(amount for _, amount in DAILY_INTERACTIONS.values()) + COMPANY_NOTES * COMPANY_STEPS


def note_amount(completed_blocks):
    return BOOST_NOTES if completed_blocks < BOOST_BLOCKS else STANDARD_NOTES


def day_segments(end, seconds):
    cursor = end - timedelta(seconds=seconds)
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
        stop = min(end, midnight)
        yield cursor.date().isoformat(), (stop - cursor).total_seconds(), stop
        cursor = stop


class PetStore:
    def __init__(self, path):
        self.growth_provider = None
        self.event_listener = None
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
          CREATE TABLE IF NOT EXISTS affection(day TEXT PRIMARY KEY, count INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS companion_notes(day TEXT NOT NULL, source TEXT NOT NULL,
            seconds REAL NOT NULL DEFAULT 0, earned INTEGER NOT NULL, PRIMARY KEY(day,source));
          CREATE TABLE IF NOT EXISTS mod_purchases(owner TEXT,item TEXT,cost INTEGER,at TEXT,
            PRIMARY KEY(owner,item));
          CREATE TABLE IF NOT EXISTS pet_shop(id INTEGER PRIMARY KEY CHECK(id=1),
            accessory TEXT NOT NULL DEFAULT '', background TEXT NOT NULL, auto_meal INTEGER NOT NULL DEFAULT 1);
        """)
        # The previous schema paid exactly two notes per completed block.
        # Keep the amount actually paid, including days already in progress.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute('INSERT OR IGNORE INTO pet_shop(id,background) VALUES(1,?)', (DEFAULT_BACKGROUND,))
            columns = {row['name'] for row in self.db.execute("PRAGMA table_info(daily)")}
            if 'earned_notes' not in columns:
                self.db.execute("ALTER TABLE daily ADD COLUMN earned_notes INTEGER NOT NULL DEFAULT 0")
                self.db.execute("ALTER TABLE daily ADD COLUMN note_seconds REAL NOT NULL DEFAULT 0")
                self.db.execute("UPDATE daily SET earned_notes=blocks*2, note_seconds=blocks*?", (REWARD_SECONDS,))
                self.db.execute("""UPDATE daily SET note_seconds=note_seconds+(SELECT progress FROM pet WHERE id=1)
                    WHERE day=(SELECT MAX(day) FROM daily WHERE seconds>0)""")

    def pet(self):
        value = dict(self.db.execute("SELECT * FROM pet WHERE id=1").fetchone())
        if self.growth_provider is not None:
            value.update(self.growth_provider())
        return value

    def emit(self, kind, **data):
        if self.event_listener is not None:
            self.event_listener(kind, data)

    def mod_owned(self, owner):
        return [row[0] for row in self.db.execute('SELECT item FROM mod_purchases WHERE owner=?',(owner,))]

    def mod_purchase(self, owner, item, cost):
        if type(cost) is not int or not 0<=cost<=10000:return False,'价格无效'
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if item in self.mod_owned(owner):return True,'已经拥有，可以直接使用'
            if self.db.execute('SELECT notes FROM pet WHERE id=1').fetchone()[0]<cost:return False,'音符不足'
            now=datetime.now()
            self.db.execute('UPDATE pet SET notes=notes-? WHERE id=1',(cost,))
            self.db.execute('INSERT INTO mod_purchases VALUES(?,?,?,?)',(owner,item,cost,now.isoformat()))
            self.db.execute('INSERT INTO ledger(at,reason,notes,xp) VALUES(?,?,?,0)',
                            (now.isoformat(),'装饰：'+owner+'/'+item,-cost))
        return True,'已获得装饰，可以反复使用'

    def _grant(self, xp, notes, reason, now):
        pet = dict(self.db.execute("SELECT * FROM pet WHERE id=1").fetchone())
        if self.growth_provider is not None:
            xp = 0
        level, value = pet['level'], pet['xp'] + xp
        while level < 30 and value >= 50 + 20 * (level - 1):
            value -= 50 + 20 * (level - 1)
            level += 1
        self.db.execute("UPDATE pet SET level=?,xp=?,notes=notes+? WHERE id=1",
                        (level, 0 if level == 30 else value, notes))
        self.db.execute("INSERT INTO ledger(at,reason,notes,xp) VALUES(?,?,?,?)",
                        (now.isoformat(), reason, notes, xp))

    def award_daily_notes(self, source, now=None):
        """Record a completed interaction and pay the wallet in the same transaction."""
        title, amount = DAILY_INTERACTIONS[source]
        now = now or datetime.now()
        with self.db:
            added = self.db.execute('INSERT INTO companion_notes(day,source,earned) VALUES(?,?,?) '
                                    'ON CONFLICT(day,source) DO NOTHING',
                                    (now.date().isoformat(), source, amount)).rowcount
            if added:
                self._grant(0, amount, '每日首次' + title, now)
        return amount if added else 0

    def _record_company(self, seconds, now):
        limit = COMPANY_STEP * COMPANY_STEPS
        for day, amount, stop in day_segments(now, seconds):
            row = self.db.execute("SELECT seconds FROM companion_notes WHERE day=? AND source='company'",
                                  (day,)).fetchone()
            before = row[0] if row else 0
            if before >= limit:
                continue
            after = min(limit, round(before + amount, 6))
            blocks = int(after // COMPANY_STEP) - int(before // COMPANY_STEP)
            notes = blocks * COMPANY_NOTES
            self.db.execute("""INSERT INTO companion_notes(day,source,seconds,earned) VALUES(?,'company',?,?)
                ON CONFLICT(day,source) DO UPDATE SET seconds=excluded.seconds, earned=earned+excluded.earned""",
                (day, after, notes))
            if notes:
                self._grant(0, notes, f'累计陪伴 {int(after // COMPANY_STEP) * COMPANY_STEP // 60} 分钟',
                            min(stop, datetime.fromisoformat(day) + timedelta(days=1, microseconds=-1)))

    def record(self, path, seconds, reward=True, end=None):
        if not 0 < seconds <= 5:
            return
        end = end or datetime.now()
        with self.db:
            for day, amount, stop in day_segments(end, seconds):
                self.db.execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
                self.db.execute("UPDATE daily SET seconds=seconds+? WHERE day=?", (amount, day))
                self.db.execute("""INSERT INTO listening(day,path,seconds) VALUES(?,?,?)
                    ON CONFLICT(day,path) DO UPDATE SET seconds=seconds+excluded.seconds""", (day,path,amount))
                daily = self.db.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
                notes = xp = 0
                if reward and daily['earned_notes'] < DAILY_NOTE_LIMIT:
                    before = daily['note_seconds']
                    after = round(before + amount, 6)
                    completed = int(before // REWARD_SECONDS)
                    if int(after // REWARD_SECONDS) > completed:
                        notes = min(note_amount(completed), DAILY_NOTE_LIMIT - daily['earned_notes'])
                    self.db.execute("UPDATE daily SET note_seconds=?, earned_notes=earned_notes+? WHERE day=?",
                                    (after, notes, day))
                if reward and daily['blocks'] < DAILY_REWARD_BLOCKS:
                    progress = self.pet()['progress'] + amount
                    blocks = min(int(progress // REWARD_SECONDS), DAILY_REWARD_BLOCKS - daily['blocks'])
                    self.db.execute("UPDATE pet SET progress=? WHERE id=1", (progress - blocks * REWARD_SECONDS,))
                    if blocks:
                        self.db.execute("UPDATE daily SET blocks=blocks+? WHERE day=?", (blocks, day))
                        xp = blocks * 5
                if xp or notes:
                    self._grant(xp, notes, '听歌奖励', stop)
                if xp and not daily['bonus']:
                    self.db.execute("UPDATE daily SET bonus=1 WHERE day=?", (day,))
                    self._grant(10, 0, '每日首次听歌', stop)
        if reward:
            self.emit('listen', seconds=seconds, source=str(path), at=end.isoformat())

    def tick_running(self, seconds, now=None):
        if not 0 < seconds <= 5:
            return
        now = now or datetime.now()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self._record_company(seconds, now)
            pet = self.db.execute('SELECT runtime,hunger,mood FROM pet WHERE id=1').fetchone()
            elapsed = pet['runtime'] + seconds
            steps = int(elapsed // 1800)
            mood = pet['mood']
            mood = max(70, mood - steps) if mood >= 70 else min(70, mood + steps)
            fullness = max(0, pet['hunger'] - steps * 5)
            self.db.execute("UPDATE pet SET hunger=?,mood=?,runtime=? WHERE id=1",
                            (fullness, mood, elapsed % 1800))
            if fullness < AUTO_FULLNESS and self.db.execute(
                    'SELECT auto_meal FROM pet_shop WHERE id=1').fetchone()[0]:
                success, _ = self._eat(AUTO_MEAL, now, automatic=True)
                if success:
                    return AUTO_MEAL

    def feed(self, food, now=None):
        now = now or datetime.now()
        item = FOOD_BY_NAME.get(food)
        if item is None:
            return False, '没有这种食物'
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            result = self._eat(item, now, automatic=False)
        if result[0]:
            self.emit('feed', food=food, at=now.isoformat())
        return result

    def _eat(self, item, now, *, automatic):
        pet = self.db.execute('SELECT hunger,notes,last_feed FROM pet WHERE id=1').fetchone()
        if pet['last_feed'] and 0 <= (now - datetime.fromisoformat(pet['last_feed'])).total_seconds() < 10:
            return False, '稍等几秒，再喂一口吧'
        if pet['hunger'] >= 95:
            return False, '已经吃饱啦'
        if pet['notes'] < item.price:
            return False, '音符不足。到小铺点「赚音符」可以查看今天的奖励。'
        earned = 0
        if not automatic:
            day = now.date().isoformat()
            self.db.execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
            feeds = self.db.execute("SELECT feeds FROM daily WHERE day=?", (day,)).fetchone()[0]
            earned = item.xp if feeds < 5 else 0
            self.db.execute("UPDATE daily SET feeds=feeds+1 WHERE day=?", (day,))
        reason = '自己买饭：' if automatic else '投喂：'
        self._grant(earned, -item.price, reason + item.name, now)
        self.db.execute('UPDATE pet SET hunger=MIN(100,hunger+?),mood=MIN(100,mood+?),last_feed=? WHERE id=1',
                        (item.fullness, item.mood, now.isoformat()))
        message = f'吃到{item.name}啦！'
        return True, message if automatic or self.growth_provider else message + f'经验 +{earned}'

    def shop_settings(self):
        return dict(self.db.execute('SELECT accessory,background,auto_meal FROM pet_shop WHERE id=1').fetchone())

    def set_auto_meal(self, enabled):
        with self.db:
            self.db.execute('UPDATE pet_shop SET auto_meal=? WHERE id=1', (int(bool(enabled)),))

    def shop_owned(self):
        return {DEFAULT_BACKGROUND, *self.mod_owned(SHOP_OWNER)}

    def buy_item(self, key, *, remove=False):
        item = ITEMS.get(key)
        if item is None:
            return False, '没有这件商品'
        if remove and item.category not in ('accessory', 'background'):
            return False, '这件商品不能取下'
        if item.category == 'food':
            return self.feed(item.name)
        now = datetime.now()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if item.category == 'gift':
                pet = self.db.execute('SELECT mood,notes FROM pet WHERE id=1').fetchone()
                if pet['mood'] >= 100:
                    return False, '今天已经很开心啦，礼物留到下次吧。'
                if pet['notes'] < item.price:
                    return False, '音符不足'
                self._grant(0, -item.price, '赠礼：' + item.name, now)
                self.db.execute('UPDATE pet SET mood=MIN(100,mood+?) WHERE id=1', (item.mood,))
                return True, f'收到{item.name}啦！心情 +{min(item.mood, 100 - pet["mood"])}'
            # Both slot names come exclusively from the fixed catalogue.
            slot = item.category
            if remove:
                self.db.execute(f"UPDATE pet_shop SET {slot}='' WHERE id=1 AND {slot}=?", (key,))
                return True, '已收起' + item.name
            if key not in self.shop_owned():
                if self.db.execute('SELECT notes FROM pet WHERE id=1').fetchone()[0] < item.price:
                    return False, '音符不足'
                self._grant(0, -item.price, '商店：' + item.name, now)
                self.db.execute('INSERT INTO mod_purchases VALUES(?,?,?,?)',
                                (SHOP_OWNER, key, item.price, now.isoformat()))
            self.db.execute(f'UPDATE pet_shop SET {slot}=? WHERE id=1', (key,))
        return True, '已换上' + item.name

    def stats(self, now=None):
        now = now or datetime.now()
        today = now.date().isoformat()
        week = (now.date() - timedelta(days=now.weekday())).isoformat()
        row = self.db.execute("SELECT seconds,earned_notes,note_seconds FROM daily WHERE day=?", (today,)).fetchone()
        weekly = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM daily WHERE day BETWEEN ? AND ?", (week,today)).fetchone()[0]
        total = self.db.execute("SELECT COALESCE(SUM(seconds),0) FROM daily").fetchone()[0]
        earned = row['earned_notes'] if row else 0
        eligible = row['note_seconds'] if row else 0
        interaction = {r['source']: r for r in self.db.execute(
            'SELECT source,seconds,earned FROM companion_notes WHERE day=?', (today,))}
        return {'today': row['seconds'] if row else 0, 'week': weekly, 'total': total,
                'reward_notes': earned, 'reward_limit': DAILY_NOTE_LIMIT,
                'daily_interactions': {source: r['earned'] for source, r in interaction.items()},
                'companion_notes': sum(r['earned'] for r in interaction.values()),
                'companion_seconds': interaction['company']['seconds'] if 'company' in interaction else 0,
                'next_reward_notes': min(note_amount(int(eligible // REWARD_SECONDS)), DAILY_NOTE_LIMIT - earned),
                'reward_remaining': None if earned >= DAILY_NOTE_LIMIT else REWARD_SECONDS - eligible % REWARD_SECONDS}

    def interact(self, now=None):
        day = (now or datetime.now()).date().isoformat()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO affection(day) VALUES(?)', (day,))
            count = self.db.execute('SELECT count FROM affection WHERE day=?', (day,)).fetchone()[0]
            if count >= 10:
                return False
            self.db.execute('UPDATE affection SET count=count+1 WHERE day=?', (day,))
            self.db.execute('UPDATE pet SET mood=MIN(100,mood+2) WHERE id=1')
        return True

    def close(self):
        self.db.close()
