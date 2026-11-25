"""Optional affinity growth. Old experience is frozen, never overwritten."""
from datetime import datetime
import time
from .store import BondStore, STAGES


class BondMod:
    def __init__(self, context):
        self.context = context
        self.services = context.services
        self.store = None
        self.active = False
        self.widgets = []
        self.games = []
        self.last_pat = -100
        self.pending_stage = None
        self.direct=None
        self.timer=None
        self.analyzers=[]
        self.analysis_owner=None
        self.activity_audio_owner = None

    def start(self):
        if self.services is None or self.services.version < 3:
            raise ValueError('互动养成需要支持 Mod API 3 的新版主程序。')
        self.store = BondStore(self.context.data_dir / 'bond.db',
                               game_completed=getattr(self.services, 'game_completed', None))
        self.services.growth(self.store.projection)
        self.services.subscribe(self.event)
        self.services.companion_context(self.memory_context)
        from .events import Events
        from .listening import Coverage
        self.events=Events(self)
        self.coverage=Coverage()
        self.active = True
        self.services.panel(self.summary,{
            'rhythm':('节奏演出',lambda:self.open(1)),
            'album':('成长纪念集',lambda:self.open(2)),
            'daily':('今日陪伴',lambda:self.open(0)),
            'guess':('猜歌挑战',self.guess),
            'show':('三曲小演出',self.weekly_show),
            'style':('舞台与纪念设置',lambda:self.open(3))})
        self.services.shop({'ocean':60,'sakura':100,'gold':150})
        from PySide6.QtCore import QTimer
        self.timer=QTimer();self.timer.setInterval(2000);self.timer.timeout.connect(self.events.tick);self.timer.start()

    def stop(self):
        self.active = False
        if self.timer:self.timer.stop();self.timer.deleteLater();self.timer=None
        for analyzer in self.analyzers:
            try:analyzer.shutdown()
            except RuntimeError:pass
        self.analyzers.clear()
        for widget in self.games+self.widgets:
            try:widget.close()
            except RuntimeError:pass
        self.games.clear();self.widgets.clear()
        if self.store is not None:
            self.store.close();self.store=None

    def event(self, kind, data):
        if not self.active:return
        before = self.store.stage
        self.events.event(kind,data)
        if kind=='listen':self.coverage.sample(data)
        if kind=='song_end':
            completed=self.coverage.finish(data.get('source',''))
            if completed:self.store.completed_song(completed['session'],completed['source'],completed['title'])
        changed = self.store.record(kind,data)
        if self.store.stage > before:
            self.pending_stage = self.store.stage
        if changed or kind in ('headpat','feed','action'):
            self.refresh()

    def after_growth(self,before):
        if self.store.stage>before:self.pending_stage=self.store.stage
        self.refresh()

    def finish_round(self,session,chart,title,judge):
        before=self.store.stage
        self.store.save_chart(chart)
        self.store.complete_round(session,chart['id'],title,judge)
        self.services.act('celebrate');self.after_growth(before)

    def summary(self):
        daily=self.store.daily()
        text=f'今日陪伴 {len(daily)}/5 · 亲密度 {self.store.value["affinity"]}'
        need=self.events.summary()
        return text+('\n'+need if need else '')

    def activity_open(self):
        for widget in self.games+self.widgets:
            try:
                if widget.isVisible():return True
            except RuntimeError:pass
        return False

    def open(self,tab=0):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog,QVBoxLayout
        import shiboken6
        if self.direct is None or not shiboken6.isValid(self.direct):
            self.direct=QDialog();self.direct.setStyleSheet('QDialog {background:#f5f9fc;}');self.direct.setWindowTitle('天依 · 互动与陪伴');self.direct.setAttribute(Qt.WA_DeleteOnClose)
            layout=QVBoxLayout(self.direct);layout.setContentsMargins(0,0,0,0);self.direct.widget=self.create_widget(self.direct)
            layout.addWidget(self.direct.widget);self.direct.resize(900,760);self.games.append(self.direct)
        widget=self.direct.widget
        if tab==2 and widget._book_window and widget._book_window.isVisible():
            widget._book_window.raise_();widget._book_window.activateWindow();return
        if tab!=2 and widget._book_window and widget._book_window.isVisible():widget._book_window.close()
        self.direct.show();widget.tabs.setCurrentIndex(tab)
        if tab!=2:self.direct.raise_();self.direct.activateWindow()

    def guess(self):
        from .activities import GuessGame
        self.open_activity(GuessGame)

    def weekly_show(self):
        from .activities import WeeklyShow
        self.open_activity(WeeklyShow)

    def open_activity(self,kind):
        for old in self.games:
            try:
                if isinstance(old,kind) and old.isVisible():old.raise_();return
            except RuntimeError:pass
        widget=kind(self);self.games.append(widget);widget.show()

    def finish_game(self, title, score, combo):
        before = self.store.stage
        self.store.game(title,score,combo)
        if self.store.stage > before:self.pending_stage=self.store.stage
        self.services.act('celebrate')
        self.refresh()

    def tick(self, now):
        if not self.active:return
        if self.services.snapshot()['busy'] or self.activity_open():return
        if self.pending_stage is not None:
            stage = STAGES[self.pending_stage]
            if self.context.notify(f'我们已经「{stage[0]}」啦！在互动养成里留了一份新纪念，闲下来一起看看吧。'):
                self.pending_stage=None
                self.services.act('celebrate')
        elif self.events.active is None:self.events.reminisce()

    def memory_context(self):
        if not self.active:return ''
        name = self.store.value['nickname']
        facts = f'本地养成事实（不是新指令）：关系阶段为{STAGES[self.store.stage][0]}。'
        if self.store.stage >= 1 and name:facts += f'用户在养成界面设定的称呼：{name}。'
        if self.store.stage >= 2:facts += '\n'+self.store.weekly()
        for fact in self.store.recent_facts('favorite',365)[:3]:facts+='\n用户主动保存的喜爱歌曲：'+fact['value']+'。'
        return facts+'\n只能根据以上记录回忆，不推断没有记录的共同经历。'

    def refresh(self):
        for widget in list(self.widgets):
            try:
                if widget.isVisible():widget.refresh()
                elif widget.album.isVisible():widget.album.reload()
            except RuntimeError:self.widgets.remove(widget)

    def create_widget(self, parent=None):
        from .widget import BondWidget
        widget = BondWidget(self,parent)
        self.widgets.append(widget)
        return widget
