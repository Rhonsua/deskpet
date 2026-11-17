"""Fact-backed needs and discoveries; all notifications share the host quota."""
from datetime import datetime,timedelta
import random
import time
import uuid


class Events:
    def __init__(self,mod):
        self.mod=mod;self.active=None;self.last_pat=-100.;self.last_check=0.;self.gazes=[];self.pats=[]
        with mod.store.db:mod.store.db.execute("UPDATE notices SET status='expired' WHERE status='waiting'")

    def event(self,kind,data):
        mod=self.mod;now=time.monotonic()
        if kind=='headpat':
            self.last_pat=now;self.pats=[x for x in self.pats if now-x<60]+[now]
            if mod.store.stage>=2 and len(self.pats)>=3:
                with mod.store.db:mod.store.card('combo:gentle','多停留一会儿的温柔','信赖以后，一次连续的摸头互动。')
        if kind=='feed' and now-self.last_pat<30:
            with mod.store.db:mod.store.card('combo:snack','摸摸之后的小点心','一次温柔互动留下的小发现。')
            self.last_pat=-100
        if kind=='action' and data.get('action')=='mouse_wave':
            self.gazes=[x for x in self.gazes if now-x<120]+[now]
            if len(self.gazes)>=3:
                with mod.store.db:mod.store.card('combo:gaze','我看见你啦','三次在手边停留后，收到了挥手回应。')
                self.gazes=[]
        if kind=='drag_end' and data.get('sway',0)>=3:
            with mod.store.db:mod.store.card('combo:sway','轻轻晃一晃','被轻轻提起，再稳稳放回了桌面。')
            mod.services.act('turn')
        if kind=='listen' and mod.services.snapshot()['state']=='sleep':
            with mod.store.db:mod.store.card('combo:dream','梦里的音符','睡着的时候，音乐仍轻轻陪着；没有叫醒她。')
        if self.active:
            if now>=self.active['deadline']:
                self.end(self.active['kind']=='quiet')
                return
            wanted=self.active['kind']
            success=(wanted==kind or wanted=='gaze' and kind=='action' and data.get('action')=='mouse_wave'
                     or wanted=='listen' and kind=='listen')
            if wanted=='quiet' and kind in ('headpat','feed','chat','action','drag_end'):
                self.end(False)
            elif success:self.end(True)

    def end(self,success):
        if not self.active:return
        event=self.active;self.active=None
        with self.mod.store.db:
            self.mod.store.db.execute('UPDATE notices SET status=? WHERE id=?',('done' if success else 'expired',event['id']))
            if success:self.mod.store.card('need:'+event['kind'],'回应了一个小心愿',event['text'])
        if success:self.mod.services.act('happy')
        self.mod.refresh()

    def summary(self):
        if not self.active:return ''
        return self.active['text']+(' 不互动就好。' if self.active['kind']=='quiet' else ' 方便时回应就好。')

    def defer(self,today=False):
        """Dismiss an invitation without a reward; persist the user's quiet choice."""
        if not self.mod.active:return False
        store=self.mod.store;now=datetime.now()
        if not self.active and not today:return False
        with store.db:
            if self.active:
                store.db.execute("UPDATE notices SET status='dismissed' WHERE id=?",(self.active['id'],))
            if today:store.configure('needs_paused_day',store.day(now))
            else:store.configure('needs_snoozed_until',(now+timedelta(minutes=30)).isoformat())
        self.active=None
        self.mod.refresh()
        return True

    def paused(self,now):
        store=self.mod.store
        day=store.preference('needs_paused_day','')
        if isinstance(day,str) and day>=store.day(now):return True
        value=store.preference('needs_snoozed_until','')
        try:return isinstance(value,str) and bool(value) and now<datetime.fromisoformat(value)
        except (ValueError,TypeError):return False

    def tick(self,now=None):
        mod=self.mod;now=now or datetime.now();clock=time.monotonic()
        if not mod.active:return
        snapshot=mod.services.snapshot()
        if self.active:
            if self.active['kind']=='quiet' and snapshot['busy']:self.end(False)
            elif clock>=self.active['deadline']:self.end(self.active['kind']=='quiet')
            return
        if clock-self.last_check<30:return
        self.last_check=clock
        if snapshot['busy'] or mod.activity_open():return
        day=mod.store.day(now)
        # Anniversaries and factual concerns get the same global throttle.
        birthday=mod.store.preference('birthday','')
        anniversary=mod.store.value['created'][5:10]
        holidays={'01-01':('新年的第一声问候','愿新的一年，也有喜欢的歌陪着你。'),
                  '07-12':('天依的生日小纪念','今天是我的生日，谢谢你来陪我！'),
                  '12-31':('一年的最后一页','这一年辛苦啦。把真实留下的小事，收进回忆里吧。')}
        if now.strftime('%m-%d') in holidays:
            title,detail=holidays[now.strftime('%m-%d')]
            with mod.store.db:mod.store.card('holiday:'+now.date().isoformat(),title,detail,now)
        if now.strftime('%m-%d')==birthday or (now.strftime('%m-%d')==anniversary and str(now.year)>mod.store.value['created'][:4]):
            key=('birthday:' if now.strftime('%m-%d')==birthday else 'anniversary:')+str(now.year)
            with mod.store.db:mod.store.card(key,'今天的小纪念','生日快乐！' if key.startswith('birthday:') else '谢谢你让我们的相遇留下了日期。',now)
        limit=mod.store.preference('needs_per_day',3)
        if not isinstance(limit,int) or not 0<limit<=5 or mod.store.stage<1:return
        if self.paused(now):return
        count=mod.store.db.execute('SELECT COUNT(*) FROM notices WHERE day=?',(day,)).fetchone()[0]
        if count>=limit:return
        choices=[('headpat','现在想被轻轻摸摸头～'),('gaze','看我这边，在我手边停一小会儿吧。'),('quiet','想和你安静待十五秒。')]
        if mod.services.library():choices.append(('listen','想和你一起听首歌，播放你喜欢的那首吧。'))
        if snapshot['hunger']<80 and snapshot['notes']>=8:choices.append(('feed','有点饿啦，想吃一口小点心。'))
        seen={r[0] for r in mod.store.db.execute('SELECT kind FROM notices WHERE day=?',(day,))}
        choices=[choice for choice in choices if choice[0] not in seen]
        if not choices:return
        kind,text=random.choice(choices)
        if mod.context.notify(text):
            key=uuid.uuid4().hex
            with mod.store.db:mod.store.db.execute('INSERT INTO notices VALUES(?,?,?,?,?)',(key,day,kind,'waiting',now.isoformat()))
            self.active=dict(id=key,kind=kind,text=text,deadline=clock+(15 if kind=='quiet' else 120))

    def reminisce(self):
        store=self.mod.store;now=datetime.now()
        fatigue=store.recent_facts('tired')
        if len({f['at'][:10] for f in fatigue})>=2:
            last=store.preference('last_care','')
            if not last or now-datetime.fromisoformat(last)>=timedelta(hours=48):
                if self.mod.context.notify('这几天你提过有些累。愿意的话，我们可以安静歇一会儿。'):
                    store.configure('last_care',now.isoformat());return
        favorites=store.recent_facts('favorite',365)
        existing={item['title'] for item in self.mod.services.library()}
        for fact in favorites:
            if fact['value'] not in existing or now-datetime.fromisoformat(fact['at'])<timedelta(days=3):continue
            last=store.preference('mentioned:'+fact['id'],'')
            if last and now-datetime.fromisoformat(last)<timedelta(days=7):continue
            if self.mod.context.notify(f'记得你说过喜欢《{fact["value"]}》。闲下来可以再一起听听。'):
                store.configure('mentioned:'+fact['id'],now.isoformat());return
