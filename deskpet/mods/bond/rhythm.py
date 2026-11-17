"""Local audio-clock performance with generated charts, holds and explicit pause."""
import math
import time
import uuid
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl,Signal,QEvent
from PySide6.QtGui import QColor,QPainter,QFont,QKeySequence
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QWidget,QPushButton,QCheckBox,QSpinBox,QKeySequenceEdit
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QSoundEffect
from .chart import generate,Judgement
from .stage_art import PALETTES,paint_stage


class Stage(QWidget):
    def __init__(self,game):
        super().__init__();self.game=game;self.mouse_lane=None
        self.theme=game.mod.store.preference('theme',None) if hasattr(game.mod.store,'preference') else None
        self.stage=game.mod.store.stage
        self.setMinimumSize(540,340);self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self,_):
        g=self.game;w,h=self.width(),self.height();lanes=g.chart['lanes'];line=h-55
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        paint_stage(p,self.rect(),self.theme,self.stage,g.elapsed if g.effects.isChecked() else 0)
        p.setPen(QColor('#8fa7cc'))
        for lane in range(1,lanes):p.drawLine(round(w*lane/lanes),0,round(w*lane/lanes),h)
        p.drawLine(0,line,w,line)
        for lane,key in enumerate(g.keys_text):
            x=round(w*(lane+.5)/lanes)
            p.setBrush(QColor('#9debea' if lane in g.round.held else '#48687e'));p.drawEllipse(x-26,line-26,52,52)
            p.setPen(QColor('white'));p.drawText(x-20,line-13,40,26,Qt.AlignCenter,key)
        travel=g.speed.value()/1000
        for n in g.round.notes:
            if n['state']=='done':continue
            x=round(w*(n['lane']+.5)/lanes)
            head=line-(n['at']-g.elapsed)*line/travel
            tail=line-(n['end']-g.elapsed)*line/travel
            if tail>h+40 or head<0:continue
            if n['type']=='hold':
                if n['state']=='holding':head=line
                p.setPen(Qt.NoPen);p.setBrush(QColor('#fae097' if n['state']=='holding' else '#9a87d5'))
                p.drawRoundedRect(x-13,max(-30,int(tail)),26,max(6,int(min(h+40,head)-max(-30,tail))),8,8)
                p.setBrush(QColor('#fff0b0'));p.drawRoundedRect(x-22,int(tail)-5,44,10,3,3)
            p.setPen(Qt.NoPen);p.setBrush(QColor('#acecf0' if n['type']=='tap' else '#ffe9a8'))
            p.drawRoundedRect(x-23,int(head)-9,46,18,7,7)
        strength=max(0,1-(time.monotonic()-g.flash)/.4)
        if strength:
            p.setPen(QColor('#fff1b3'));p.setFont(QFont(self.font().family(),20,QFont.Bold))
            p.drawText(self.rect().adjusted(0,24,0,-70),Qt.AlignTop|Qt.AlignHCenter,g.feedback)
            if g.effects.isChecked():
                p.setPen(Qt.NoPen);p.setBrush(QColor(255,233,158,int(210*strength)))
                for i in range(12):
                    angle=i*math.tau/12;radius=15+(1-strength)*80
                    p.drawEllipse(round(w*(g.flash_lane+.5)/lanes+math.cos(angle)*radius),round(line+math.sin(angle)*radius),5,5)
        if g.effects.isChecked() and g.round.combo>=10:
            p.setPen(Qt.NoPen);p.setBrush(QColor(190,235,255,100))
            for i in range(min(16,g.round.combo//3)):
                p.drawEllipse(round((i+.5)*w/16),round(20+math.sin(g.elapsed*2+i)*12),5,5)
        if g.paused:
            p.fillRect(self.rect(),QColor(0,0,0,100));p.setPen(Qt.white)
            p.drawText(self.rect(),Qt.AlignCenter,'已暂停 · 按住长条对应按键后继续')
        p.end()

    def keyPressEvent(self,e):
        if not e.isAutoRepeat() and e.key() in self.game.keys:self.game.press(self.game.keys.index(e.key()))
        else:super().keyPressEvent(e)

    def keyReleaseEvent(self,e):
        if not e.isAutoRepeat() and e.key() in self.game.keys:self.game.release(self.game.keys.index(e.key()))
        else:super().keyReleaseEvent(e)

    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton:
            self.mouse_lane=min(self.game.chart['lanes']-1,max(0,int(e.position().x()*self.game.chart['lanes']/self.width())))
            self.game.press(self.mouse_lane);self.setFocus()

    def mouseReleaseEvent(self,e):
        if e.button()==Qt.LeftButton and self.mouse_lane is not None:
            self.game.release(self.mouse_lane);self.mouse_lane=None


class RhythmGame(QDialog):
    completed=Signal()
    def __init__(self,mod,source='',bpm=120,parent=None,*,chart=None):
        super().__init__(parent)
        self.mod,self.source=mod,source;self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle('天依 · 节奏演出');self.resize(720,580)
        self.duration=40.;self.offset=0.;self.title=Path(source).stem if source else '离线节拍练习'
        snapshot=mod.services.snapshot(music=True)
        if source:
            from mutagen import File
            info=File(source)
            if info is None or not info.info or info.info.length<35:raise ValueError('歌曲至少需要 35 秒')
            self.duration=min(40,info.info.length-4);self.offset=min(info.info.length-self.duration-1,info.info.length*.3)
        if chart is None:
            analysis=snapshot['beats'] if snapshot['beat_source']=='local:'+source and source else {}
            chart=generate(analysis,source=source,offset=self.offset,duration=self.duration,bpm=bpm,seed=int(uuid.uuid4().hex[:8],16))
        self.chart=chart;self.duration=chart['duration'];self.offset=chart['offset'];self.round=Judgement(chart)
        self.keys_text=('D','F','J') if chart['lanes']==3 else ('D','F','J','K')
        self.keys=tuple(getattr(Qt,'Key_'+key) for key in self.keys_text)
        configured=mod.store.preference('keys:'+str(chart['lanes']),None)
        if isinstance(configured,list) and len(configured)==chart['lanes'] and len(set(configured))==len(configured) and all(type(x) is int and 32<=x<=90 for x in configured):
            self.keys=tuple(configured);self.keys_text=tuple(QKeySequence(key).toString() for key in configured)
        self.session=uuid.uuid4().hex;self.token=None;self.elapsed=0.;self.started=None
        self.requested=False;self.finished=False;self.paused=False;self.resume_keys=set();self.resume_wait=False
        self.flash=0.;self.flash_lane=1;self.feedback='';self.last_elapsed=0.;self.last_advance=time.monotonic();self.last_actor=0
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(snapshot.get('volume',.5))
        self.router=mod.services.audio_route(self.audio,self) if hasattr(mod.services,'audio_route') else None
        self.player.setAudioOutput(self.audio);self.player.errorOccurred.connect(self.failed);self.player.mediaStatusChanged.connect(self.loaded)
        self.effect=None
        box=QVBoxLayout(self);self.label=QLabel(self.title+'\n'+('节拍练习谱' if chart['practice'] else '歌曲拍点谱')+' · 单点 / 长条'+(' / 双押' if chart['difficulty']!='easy' and chart['input']!='mouse' else ''))
        self.label.setTextFormat(Qt.PlainText);self.label.setWordWrap(True);box.addWidget(self.label)
        self.stage=Stage(self);box.addWidget(self.stage,1)
        self.score=QLabel('按住长条到尾部 · 失误不会中断音乐');box.addWidget(self.score)
        options=QHBoxLayout()
        self.sound=QCheckBox('判定音');self.sound.setChecked(True);options.addWidget(self.sound)
        self.effects=QCheckBox('舞台光效');self.effects.setChecked(True);options.addWidget(self.effects)
        options.addWidget(QLabel('可见提前量'))
        self.speed=QSpinBox();self.speed.setRange(800,4000);self.speed.setValue(2000);self.speed.setSuffix(' ms');options.addWidget(self.speed)
        options.addWidget(QLabel('输入偏移'))
        self.offset_control=QSpinBox();self.offset_control.setRange(-500,500);self.offset_control.setSuffix(' ms')
        self.offset_control.setValue(mod.store.preference('input_offset',0) if hasattr(mod.store,'preference') else 0)
        options.addWidget(self.offset_control);box.addLayout(options)
        row=QHBoxLayout();self.start_button=QPushButton('开始演出');self.start_button.clicked.connect(self.start);row.addWidget(self.start_button)
        self.pause_button=QPushButton('暂停 / 继续');self.pause_button.setEnabled(False);self.pause_button.clicked.connect(self.toggle_pause);row.addWidget(self.pause_button)
        self.favorite=QPushButton('收藏这份谱');self.favorite.clicked.connect(self.save_chart);row.addWidget(self.favorite);box.addLayout(row)
        self.key_button=QPushButton('调整按键');self.key_button.clicked.connect(self.configure_keys);row.addWidget(self.key_button)
        self.timer=QTimer(self);self.timer.setInterval(16);self.timer.timeout.connect(self.update_game)
        self.countdown=QTimer(self);self.countdown.setSingleShot(True);self.countdown.timeout.connect(self.resume)

    def now(self):
        if self.started is None:return 0.
        return self.player.position()/1000-self.offset if self.source else time.monotonic()-self.started

    def save_chart(self):
        try:self.mod.store.save_chart(self.chart,True);self.favorite.setText('已收藏，可从演出页重玩')
        except Exception:self.label.setText('谱面保存失败，请检查磁盘空间。')

    def start(self):
        if self.requested or self.finished or not self.mod.active:return
        if self.mod.services.snapshot()['playing']:
            self.label.setText('请先暂停普通播放，再开始演出。');return
        self.token=self.mod.services.audio_claim()
        if not self.token:self.label.setText('另一个互动正在使用声音，请先结束它。');return
        self.requested=True;self.start_button.setEnabled(False);self.offset_control.setEnabled(False)
        self.key_button.setEnabled(False)
        self.mod.store.configure('input_offset',self.offset_control.value())
        self.last_advance=time.monotonic()
        if self.source:
            self.player.setSource(QUrl.fromLocalFile(self.source));QTimer.singleShot(20000,self,self.loading_timeout)
        else:self.started=time.monotonic();self.timer.start();self.pause_button.setEnabled(True)
        self.stage.setFocus()

    def configure_keys(self):
        if self.requested:return
        dialog=QDialog(self);dialog.setWindowTitle('演出按键');box=QVBoxLayout(dialog)
        message=QLabel('每条轨道设置一个字母、数字或空格，不可重复。');message.setWordWrap(True);box.addWidget(message)
        fields=[]
        for i,key in enumerate(self.keys):
            box.addWidget(QLabel(f'第 {i+1} 轨'));edit=QKeySequenceEdit(QKeySequence(key));edit.setMaximumSequenceLength(1);box.addWidget(edit);fields.append(edit)
        button=QPushButton('保存');box.addWidget(button)
        def save():
            values=[]
            for edit in fields:
                sequence=edit.keySequence()
                if sequence.count()!=1 or sequence[0].keyboardModifiers()!=Qt.NoModifier:message.setText('请使用没有组合键的单个按键。');return
                values.append(int(sequence[0].key()))
            if len(set(values))!=len(values) or any(not (x==32 or 48<=x<=57 or 65<=x<=90) for x in values):message.setText('请使用互不相同的字母、数字或空格。');return
            self.keys=tuple(values);self.keys_text=tuple(QKeySequence(key).toString() for key in values)
            self.mod.store.configure('keys:'+str(self.chart['lanes']),values);self.stage.update();dialog.accept()
        button.clicked.connect(save);dialog.exec()

    def keyPressEvent(self,event):
        if not event.isAutoRepeat() and event.key() in self.keys:self.press(self.keys.index(event.key()));event.accept()
        else:super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if not event.isAutoRepeat() and event.key() in self.keys:self.release(self.keys.index(event.key()));event.accept()
        else:super().keyReleaseEvent(event)

    def loaded(self,status):
        if self.finished or not self.requested or not self.mod.active:return
        if status==QMediaPlayer.EndOfMedia:
            if self.elapsed>=self.duration-.2:self.finish()
            else:self.failed()
        elif status==QMediaPlayer.LoadedMedia and self.started is None:
            self.player.setPosition(round(self.offset*1000));self.player.play()
            self.started=self.last_advance=time.monotonic();self.timer.start();self.pause_button.setEnabled(True)
            self.mod.services.act('sing')

    def loading_timeout(self):
        if self.requested and self.started is None and not self.finished:self.failed()

    def press(self,lane):
        if self.started is None or self.finished:return
        if self.paused:
            self.resume_keys.add(lane);return
        self.elapsed=self.now();self.feedback=self.round.press(lane,self.elapsed+self.offset_control.value()/1000)
        if self.feedback:
            self.flash=time.monotonic();self.flash_lane=lane;self.play_tap()
            if self.round.combo and self.round.combo%10==0:self.mod.services.act('turn' if self.round.combo>=20 else 'happy')
        self.stage.update()

    def hit(self,lane):self.press(lane)

    def release(self,lane):
        self.resume_keys.discard(lane)
        if self.started is not None and not self.finished and not self.paused:
            self.round.release(lane,self.now()+self.offset_control.value()/1000)

    def toggle_pause(self):
        if self.finished or self.started is None:return
        if not self.paused:self.pause()
        elif not self.resume_wait:
            self.resume_wait=True;self.label.setText('准备继续：2 秒；长条可以提前按住对应键。')
            self.stage.setFocus();self.countdown.start(2000)

    def pause(self):
        if self.paused or self.finished or self.started is None:return
        self.elapsed=self.now();self.round.suspend(self.elapsed+self.offset_control.value()/1000)
        self.paused=True;self.resume_keys.clear();self.player.pause();self.stage.update()
        if self.effect:self.effect.stop()

    def resume(self):
        self.resume_wait=False
        if not self.paused or self.finished or not self.mod.active:return
        self.round.held=set(self.resume_keys);self.round.rearm();self.paused=False
        self.started=time.monotonic()-self.elapsed;self.last_advance=time.monotonic()
        if self.source:self.player.play()
        self.label.setText(self.title);self.stage.setFocus()

    def event(self,event):
        if event.type()==QEvent.WindowDeactivate and hasattr(self,'paused'):
            self.countdown.stop();self.resume_wait=False;self.pause()
        return super().event(event)

    def play_tap(self):
        if not self.sound.isChecked():return
        if self.effect is None:
            import struct,wave
            try:
                path=self.mod.context.data_dir/'tap.wav'
                if not path.exists():
                    samples=[int(8000*math.exp(-i/600)*math.sin(math.tau*880*i/22050)) for i in range(1764)]
                    with wave.open(str(path),'wb') as out:
                        out.setnchannels(1);out.setsampwidth(2);out.setframerate(22050);out.writeframes(struct.pack('<'+'h'*len(samples),*samples))
                self.effect=QSoundEffect(self);self.effect.setSource(QUrl.fromLocalFile(str(path)))
            except (OSError,ValueError):return
        self.effect.setVolume(.3*self.mod.services.snapshot().get('volume',.5));self.effect.play()

    def update_game(self):
        if self.finished or self.started is None:return
        if not self.mod.active:self.close();return
        if self.mod.services.snapshot()['playing'] or not self.mod.services.audio_valid(self.token):self.failed();return
        if self.paused:return
        self.elapsed=self.now()
        if self.elapsed>self.last_elapsed:
            self.last_advance=time.monotonic();self.last_elapsed=self.elapsed
        elif time.monotonic()-self.last_advance>20:self.failed();return
        if self.source and self.player.playbackState()!=QMediaPlayer.PlayingState:return
        self.round.advance(self.elapsed+self.offset_control.value()/1000);self.stage.update()
        self.score.setText(f'得分 {self.round.score:,} · 连击 {self.round.combo} · 长条 {self.round.holds} · 剩余 {max(0,int(self.duration-self.elapsed))} 秒')
        if time.monotonic()-self.last_actor>3:
            self.last_actor=time.monotonic();self.mod.services.act('sing')
        if self.elapsed>=self.duration:self.finish()

    def finish(self):
        if self.finished:return
        self.finished=True;self.release_audio()
        self.round.advance(self.duration+1)
        eligible=self.round.hits>=min(5,len(self.round.notes)) and bool(self.round.notes)
        if eligible:
            self.mod.finish_round(self.session,self.chart,self.title,self.round)
            best=self.mod.store.best(self.chart['id'])
            self.label.setText(f'一起完成啦！准确率 {self.round.score/10000:.2f}%\n完美 {self.round.perfect} · 良好 {self.round.good} · 失误 {self.round.misses} · 同谱最高 {best[0]:,}')
        else:self.label.setText('这次先熟悉节奏，下次跟着音符多试几拍就好。未计入每日成长。')
        self.start_button.setText('原谱再来一次');self.start_button.setEnabled(True)
        self.start_button.clicked.disconnect();self.start_button.clicked.connect(self.retry)
        self.completed.emit()

    def retry(self):
        if not self.mod.active:return
        game=RhythmGame(self.mod,self.source,parent=self.parentWidget(),chart=self.chart)
        self.mod.games.append(game);game.show();self.close()

    def release_audio(self):
        self.timer.stop();self.countdown.stop();self.pause_button.setEnabled(False);self.player.stop()
        self.player.setSource(QUrl())
        if self.router:self.router.poll.stop()
        if self.effect:self.effect.stop()
        if self.token:self.mod.services.audio_release(self.token);self.token=None

    def failed(self,*_):
        if self.finished:return
        self.finished=True;self.release_audio();self.start_button.setEnabled(False)
        self.label.setText('演出已停止，没有发放完成奖励。请检查歌曲，或先结束其他播放再试。')

    def closeEvent(self,event):
        self.finished=True;self.release_audio();super().closeEvent(event)
