"""Offline facts and once-per-day growth; no LLM-generated shared history."""
from datetime import datetime, timedelta
import sqlite3
import json
from pathlib import Path

STAGES = [('初识', 0, '节奏练习、每日互动、基础纪念册'),
          ('熟悉', 40, '专属称呼、星光配色舞台'),
          ('信赖', 150, '本周回忆、回忆卡导出'),
          ('默契', 350, '极光配色舞台、默契阶段纪念'),
          ('知心', 700, '暮色配色舞台、知心阶段纪念'),
          ('陪伴', 1400, '金色纪念舞台、陪伴阶段纪念')]
CATEGORIES = {'headpat':'摸摸头', 'feed':'照料 / 投喂', 'chat':'说说话', 'listen':'听歌 / 安静陪伴 10 分钟', 'game':'完成演出 / 猜歌'}
ACTION_NAMES = {'headpat':'摸摸头', 'feed':'一起吃点心', 'happy':'开心', 'mouse_wave':'挥挥手',
                'turn':'转身', 'level_up':'庆祝', 'eat':'吃点心', 'sleep':'晚安', 'sing':'持麦唱歌'}


class BondStore:
    def __init__(self, path):
        self.path=Path(path)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        if self.db.execute('PRAGMA user_version').fetchone()[0]>2:
            self.db.close();raise ValueError('存档来自更新版本的养成包，请更新后再启用。')
        if self.db.execute('PRAGMA user_version').fetchone()[0]<2 and self.db.execute("SELECT name FROM sqlite_master WHERE name='state'").fetchone():
            backup=sqlite3.connect(str(self.path.with_name('bond.previous.db')))
            try:self.db.backup(backup)
            finally:backup.close()
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), affinity INTEGER NOT NULL DEFAULT 0,
            day TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS daily(day TEXT, kind TEXT, PRIMARY KEY(day,kind));
          CREATE TABLE IF NOT EXISTS listening(day TEXT, title TEXT, seconds REAL NOT NULL DEFAULT 0, PRIMARY KEY(day,title));
          CREATE TABLE IF NOT EXISTS collection(id TEXT PRIMARY KEY, title TEXT, at TEXT, detail TEXT);
          CREATE TABLE IF NOT EXISTS games(at TEXT, song TEXT, score INTEGER, combo INTEGER);
          CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE IF NOT EXISTS charts(id TEXT PRIMARY KEY,body TEXT,favorite INTEGER DEFAULT 0,at TEXT);
          CREATE TABLE IF NOT EXISTS results(session TEXT PRIMARY KEY,chart TEXT,song TEXT,at TEXT,score INTEGER,
            combo INTEGER,perfect INTEGER,good INTEGER,misses INTEGER,holds INTEGER,completed INTEGER,kind TEXT);
          CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,day TEXT,kind TEXT,status TEXT,at TEXT);
          CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,kind TEXT,value TEXT,at TEXT);
          CREATE TABLE IF NOT EXISTS song_completions(session TEXT PRIMARY KEY,source TEXT,title TEXT,at TEXT);
          CREATE TABLE IF NOT EXISTS shows(session TEXT PRIMARY KEY,body TEXT,at TEXT);
          PRAGMA user_version=2;
        ''')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO state(id,created) VALUES(1,?)', (datetime.now().isoformat(),))
            self.card('first-meeting', '第一次相遇', '从今天开始，把真正发生的小事慢慢记下来。')
        self.refresh()
        self._read_cache={}
        self._mutation_serial=0
        self.db.create_function('bond_next_revision',0,self._next_revision)
        self._revision_tables=('state','daily','listening','collection','games','preferences','charts',
                               'results','notices','facts','song_completions','shows')
        # Connection-local revisions also cover writes from UI transactions. They roll
        # back with the write and do not add persistent tables or change save format.
        self.db.execute('CREATE TEMP TABLE bond_revisions(name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        for table in self._revision_tables:
            self.db.execute('INSERT INTO bond_revisions VALUES(?,0)',(table,))
            for operation in ('INSERT','UPDATE','DELETE'):
                self.db.execute(f'''CREATE TEMP TRIGGER bond_{table}_{operation.lower()}
                  AFTER {operation} ON main.{table} BEGIN
                  UPDATE bond_revisions SET value=bond_next_revision() WHERE name='{table}'; END''')
        self.db.commit()
        self._revision_changes=-1
        self._revisions={}
        self._external_version=None

    def _next_revision(self):
        # SQLite rolls TEMP rows back too. A Python serial never rolls back, so
        # the next write cannot reuse a stamp cached inside an aborted transaction.
        self._mutation_serial+=1
        return self._mutation_serial

    def revision(self,*tables):
        if any(table not in self._revision_tables for table in tables):raise ValueError('Unknown revision scope')
        external=self.db.execute('PRAGMA data_version').fetchone()[0]
        changes=self.db.total_changes
        if self.db.in_transaction or changes!=self._revision_changes or external!=self._external_version:
            self._revisions=dict(self.db.execute('SELECT name,value FROM bond_revisions'))
            self._revision_changes=-1 if self.db.in_transaction else changes
            self._external_version=external
        return (external,)+tuple(self._revisions[table] for table in tables)

    def _cached(self,key,stamp,read):
        previous=self._read_cache.get(key)
        if previous is None or previous[0]!=stamp:
            previous=(stamp,read());self._read_cache[key]=previous
        return previous[1]

    def refresh(self):
        self.value = dict(self.db.execute('SELECT * FROM state WHERE id=1').fetchone())

    @property
    def stage(self):
        return max(i for i, (_, goal, _) in enumerate(STAGES) if self.value['affinity'] >= goal)

    def projection(self):
        stage = self.stage
        start = STAGES[stage][1]
        goal = STAGES[stage+1][1]-start if stage < 5 else 1
        return dict(level=stage+1, xp=min(goal, self.value['affinity']-start) if stage < 5 else 1,
                    xp_goal=goal, stage=STAGES[stage][0], affinity=self.value['affinity'], growth_label='亲密度')

    def day(self, now):
        # Clock rollback cannot reopen an older day's reward slots.
        return max(now.date().isoformat(), self.value['day'])

    def card(self, key, title, detail='', now=None):
        self.db.execute('INSERT OR IGNORE INTO collection VALUES(?,?,?,?)',
            (key, title[:100], (now or datetime.now()).isoformat(timespec='seconds'), detail[:1000]))

    def award(self, kind, now=None):
        if kind not in CATEGORIES:
            return False
        now = now or datetime.now()
        day, before = self.day(now), self.stage
        with self.db:
            added = self.db.execute('INSERT OR IGNORE INTO daily VALUES(?,?)', (day,kind)).rowcount
            if added:
                self.db.execute('UPDATE state SET affinity=MIN(affinity+10,100000),day=? WHERE id=1', (day,))
                self.refresh()
                for stage in range(before+1, self.stage+1):
                    self.card('stage:'+str(stage), '我们已经'+STAGES[stage][0]+'啦', STAGES[stage][2], now)
        self.refresh()
        return bool(added)

    def record(self, kind, data, now=None):
        now = now or datetime.now()
        if kind == 'listen':
            seconds = data.get('seconds', 0)
            if not isinstance(seconds, (int,float)) or not 0 < seconds <= 5:
                return False
            title = str(data.get('title') or '未命名歌曲')[:160]
            day = self.day(now)
            with self.db:
                if day > self.value['day']:
                    self.db.execute('UPDATE state SET day=? WHERE id=1', (day,))
                    self.refresh()
                self.db.execute('INSERT INTO listening VALUES(?,?,?) ON CONFLICT(day,title) DO UPDATE SET seconds=seconds+excluded.seconds',
                                (day,title,seconds))
            elapsed = self.db.execute('SELECT COALESCE(SUM(seconds),0) FROM listening WHERE day=?', (self.day(now),)).fetchone()[0]
            return self.award('listen',now) if elapsed >= 600 else False
        if kind in ('headpat','feed','action'):
            action = data.get('action') if kind == 'action' else kind
            if action in ACTION_NAMES:
                with self.db:
                    self.card('action:'+action, ACTION_NAMES[action], '亲自触发后收录', now)
        return self.award(kind,now)

    def game(self, song, score, combo, now=None):
        now = now or datetime.now()
        with self.db:
            self.db.execute('INSERT INTO games VALUES(?,?,?,?)', (now.isoformat(),song[:160],score,combo))
            self.card('first-performance', '第一次节奏演出', '谢谢你为我打拍子，失误也没关系。',now)
        return self.award('game',now)

    def daily(self, now=None):
        now = now or datetime.now()
        return {row[0] for row in self.db.execute('SELECT kind FROM daily WHERE day=?',(self.day(now),))}

    def listen_seconds(self, now=None):
        return self.db.execute('SELECT COALESCE(SUM(seconds),0) FROM listening WHERE day=?',
                               (self.day(now or datetime.now()),)).fetchone()[0]

    def memories(self):
        rows=self._cached('memories',self.revision('collection'),
            lambda:tuple(tuple(r) for r in self.db.execute('SELECT id,title,at,detail FROM collection ORDER BY at DESC,id')))
        return [dict(zip(('id','title','at','detail'),r)) for r in rows]

    def weekly(self, now=None):
        now = now or datetime.now()
        start = (now.date()-timedelta(days=now.weekday())).isoformat()
        end = now.date().isoformat()
        songs = list(self.db.execute('SELECT title,SUM(seconds) AS seconds FROM listening WHERE day BETWEEN ? AND ? GROUP BY title ORDER BY seconds DESC LIMIT 8',(start,end)))
        counts = dict(self.db.execute('SELECT kind,COUNT(*) FROM daily WHERE day BETWEEN ? AND ? GROUP BY kind',(start,end)))
        lines = [f'{start} ～ {end} · 本地记录']
        lines += [f'{CATEGORIES[k]}：{v} 天' for k,v in counts.items() if k in CATEGORIES]
        lines += [f'一起听过《{r[0]}》约 {int(r[1]//60)} 分钟' for r in songs if r[1] >= 60]
        diary=self.db.execute("SELECT at,detail FROM collection WHERE id LIKE 'diary:%' AND substr(at,1,10) BETWEEN ? AND ? ORDER BY at LIMIT 5",(start,end))
        lines += [f'{r[0][:10]} 用户留下的话：{r[1][:100]}' for r in diary]
        shows=self.db.execute('SELECT COUNT(*) FROM shows WHERE substr(at,1,10) BETWEEN ? AND ?',(start,end)).fetchone()[0]
        if shows:lines.append(f'共同完成三曲演出 {shows} 次')
        return '\n'.join(lines + (['这一周还没有记录，慢慢来就好。'] if len(lines)==1 else []))

    def nickname(self, value):
        with self.db:
            self.db.execute('UPDATE state SET nickname=? WHERE id=1',(value.strip()[:20],))
        self.refresh()

    def close(self):
        self.db.close()

    def preference(self,key,default=None):
        row=self.db.execute('SELECT value FROM preferences WHERE key=?',(key,)).fetchone()
        try:return json.loads(row[0]) if row else default
        except (ValueError,TypeError):return default

    def configure(self,key,value):
        with self.db:self.db.execute('INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                                    (key,json.dumps(value,ensure_ascii=False)))

    def save_chart(self,chart, favorite=False):
        from .chart import validate,digest
        validate(chart)
        if chart.get('id')!=digest(chart):raise ValueError('谱面校验失败')
        with self.db:
            self.db.execute('INSERT INTO charts VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET favorite=MAX(favorite,excluded.favorite)',
                (chart['id'],json.dumps(chart,ensure_ascii=False),int(favorite),datetime.now().isoformat()))
            self.db.execute('DELETE FROM charts WHERE favorite=0 AND id NOT IN (SELECT id FROM charts WHERE favorite=0 ORDER BY at DESC LIMIT 100)')

    def chart(self,key):
        row=self.db.execute('SELECT body FROM charts WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def favorite_charts(self):
        return [(r[0],json.loads(r[1])) for r in self.db.execute('SELECT id,body FROM charts WHERE favorite=1 ORDER BY at DESC')]

    def favorite_chart_summaries(self):
        def read():
            result=[]
            for key,body in self.db.execute('SELECT id,body FROM charts WHERE favorite=1 ORDER BY at DESC'):
                chart=json.loads(body)
                result.append((key,str(chart.get('source','')),str(chart.get('difficulty','normal'))))
            return tuple(result)
        return [(key,dict(source=source,difficulty=difficulty)) for key,source,difficulty in
                self._cached('chart_summaries',self.revision('charts'),read)]

    def complete_round(self, session, chart, title, judge, *, kind='rhythm', now=None):
        now=now or datetime.now()
        if self.db.execute('SELECT 1 FROM results WHERE session=?',(session,)).fetchone():return False
        with self.db:
            self.db.execute('INSERT INTO results VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (session,chart,title[:160],now.isoformat(),judge.score,judge.best,judge.perfect,judge.good,judge.misses,judge.holds,1,kind))
            self.card('first-'+kind,'第一次'+('猜歌挑战' if kind=='quiz' else '节奏演出'),'这次一起完成的小演出。',now)
            return self.award('game',now)

    def best(self,chart):
        row=self.db.execute('SELECT MAX(score),MAX(combo) FROM results WHERE chart=?',(chart,)).fetchone()
        return (row[0] or 0,row[1] or 0)

    def fact(self,kind,value,now=None):
        from uuid import uuid4
        now=now or datetime.now()
        with self.db:self.db.execute('INSERT INTO facts VALUES(?,?,?,?)',(uuid4().hex,kind,str(value)[:500],now.isoformat()))

    def recent_facts(self,kind,days=7,now=None):
        now=now or datetime.now()
        return [dict(r) for r in self.db.execute('SELECT * FROM facts WHERE kind=? AND at>=? ORDER BY at DESC',
                (kind,(now-timedelta(days=days)).isoformat()))]

    def forget(self,key):
        with self.db:
            self.db.execute('DELETE FROM facts WHERE id=?',(key,))
            self.db.execute('DELETE FROM collection WHERE id=?',(key,))

    def completed_song(self,session,source,title,now=None):
        now=now or datetime.now()
        with self.db:
            added=self.db.execute('INSERT OR IGNORE INTO song_completions VALUES(?,?,?,?)',
                                 (session,source,title[:160],now.isoformat())).rowcount
            count=self.db.execute('SELECT COUNT(*) FROM song_completions WHERE source=?',(source,)).fetchone()[0]
            for n in (1,3,10):
                if count>=n:self.card('song:'+source+':'+str(n),f'唱片纪念 · {title[:80]}',f'已共同完整听完 {n} 次。',now)
        return bool(added)

    def record_show(self,session,program,now=None):
        now=now or datetime.now()
        with self.db:
            added=self.db.execute('INSERT OR IGNORE INTO shows VALUES(?,?,?)',
                                 (session,json.dumps(program,ensure_ascii=False),now.isoformat())).rowcount
            if added:self.card('show:'+session,'我们的三曲小演出',' · '.join(p['title'] for p in program),now)
            if added:
                self.card('show:first','第一次完整谢幕','三首歌曲连成了一段小小的舞台时光。',now)
                week=now.strftime('%G-W%V')
                self.card('show:week:'+week,'本周的小演出',now.date().isoformat()+' · '+'、'.join(p['title'] for p in program),now)
        return bool(added)
