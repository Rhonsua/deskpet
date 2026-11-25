"""Local audio-clock performance with generated charts, holds and explicit pause."""
import math
import time
import uuid
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl,Signal,QEvent,QRectF
from PySide6.QtGui import QColor,QPainter,QFont,QKeySequence,QPixmap,QPen
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QWidget,QPushButton,QCheckBox,QSpinBox,QKeySequenceEdit
from .chart import generate,Judgement
from .playback import ClipPlayer
from .scrapbook import activity_images
from .stage_art import paint_stage, stage_image
from .studio import activity_style, dark_theme


class Stage(QWidget):
    def __init__(self,game):
        super().__init__();self.game=game;self.mouse_lane=None
        self.theme=game.mod.store.preference('theme',None) if hasattr(game.mod.store,'preference') else None
        self.stage=game.mod.store.stage
        self.setMinimumSize(400,285);self.setFocusPolicy(Qt.StrongFocus)
        self.backdrop = None
        self.backdrop_key = None
        activity_images().ready.connect(self.update)

    def stage_backdrop(self, lanes, line):
        ratio = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        key = (w, h, ratio, self.theme, self.stage, lanes, stage_image('stage-scenery').cacheKey())
        if key == self.backdrop_key:
            return self.backdrop
        surface = QPixmap(round(w*ratio), round(h*ratio))
        surface.setDevicePixelRatio(ratio)
        surface.fill(QColor('#172737'))
        p = QPainter(surface)
        p.setRenderHint(QPainter.Antialiasing)
        paint_stage(p, self.rect(), self.theme, self.stage)
        lane_width = w / lanes
        for lane in range(lanes):
            bounds = QRectF(lane*lane_width+2, 0, lane_width-4, line+11)
            p.fillRect(bounds, QColor(11,25,40,200 if lane%2 else 184))
            if lane:
                p.setPen(QPen(QColor(205,230,226,111), 1))
                p.drawLine(round(lane*lane_width),0,round(lane*lane_width),line+10)
        p.fillRect(QRectF(0,line+10,w,h-line-10),QColor('#1a2d3c'))
        p.fillRect(QRectF(0,line-3,w,6), QColor(140,225,210,72))
        p.fillRect(QRectF(0,line-1,w,2), QColor('#c2f3df'))
        p.end()
        self.backdrop_key, self.backdrop = key, surface
        return surface

    def paintEvent(self,_):
        g=self.game;w,h=self.width(),self.height();lanes=g.chart['lanes'];line=h-52
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(0,0,self.stage_backdrop(lanes,line))
        cap_width = min(80., w/lanes*.52)
        p.setFont(QFont(self.font().family(),11,QFont.Bold))
        for lane,key in enumerate(g.keys_text):
            x = w*(lane+.5)/lanes
            held = lane in g.round.held
            slot = QRectF(x-cap_width/2, line+15, cap_width, 28)
            p.setPen(QPen(QColor('#a1dcd5' if held else '#6d929b'), 1.3))
            p.setBrush(QColor('#a1dcd5' if held else '#293f4d'))
            p.drawRoundedRect(slot, 7, 7)
            p.setPen(QColor('#163741' if held else '#eef7ef'))
            p.drawText(slot, Qt.AlignCenter, key)
            if held:
                p.fillRect(QRectF(x-cap_width*.62,line-2,cap_width*1.24,4),QColor('#ffe394'))
        travel=g.speed.value()/1000
        for n in g.round.notes:
            if n['state']=='done':continue
            x=round(w*(n['lane']+.5)/lanes)
            head=line-(n['at']-g.elapsed)*line/travel
            tail=line-(n['end']-g.elapsed)*line/travel
            if tail>h+40 or head<0:continue
            if n['type']=='hold':
                if n['state']=='holding':head=line
                top = max(-12., tail)
                length = max(3., min(h+16.,head)-top)
                stem = cap_width*.38
                p.setPen(Qt.NoPen)
                p.setBrush(QColor('#f9d279' if n['state']=='holding' else '#d8a96d'))
                p.drawRoundedRect(QRectF(x-stem/2,top,stem,length),5,5)
                p.fillRect(QRectF(x-1,top,2,length),QColor('#ffe7b6'))
                p.setBrush(QColor('#fff0c3'))
                p.drawRoundedRect(QRectF(x-cap_width*.36,tail-3,cap_width*.72,6),3,3)
            is_hold = n['type']=='hold'
            p.setPen(Qt.NoPen);p.setBrush(QColor('#163342'))
            p.drawRoundedRect(QRectF(x-cap_width/2,head-6,cap_width,16),5,5)
            p.setBrush(QColor('#f5ca87' if is_hold else '#99e5d8'))
            p.drawRoundedRect(QRectF(x-cap_width/2,head-8,cap_width,14),5,5)
            p.setBrush(QColor('#fff5db' if is_hold else '#dbfff4'))
            p.drawRoundedRect(QRectF(x-cap_width*.26,head-5,cap_width*.52,3),1.5,1.5)
        strength=max(0,1-(time.monotonic()-g.flash)/.4)
        if strength:
            p.setPen(QColor('#ffe39b' if g.feedback=='完美' else '#c4f1e9'));p.setFont(QFont(self.font().family(),20,QFont.Bold))
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
        self.setStyleSheet(activity_style(dark_theme()))
        self.duration=40.;self.offset=0.;self.title=Path(source).stem if source else '离线节拍练习'
        if chart is None:
            snapshot=mod.services.snapshot(music=True)
            if source:
                from mutagen import File
                info=File(source)
                if info is None or not info.info or info.info.length<35:raise ValueError('歌曲至少需要 35 秒')
                self.duration=min(40,info.info.length-4);self.offset=min(info.info.length-self.duration-1,info.info.length*.3)
            analysis=snapshot['beats'] if snapshot['beat_source']=='local:'+source and source else {}
            chart=generate(analysis,source=source,offset=self.offset,duration=self.duration,bpm=bpm,seed=int(uuid.uuid4().hex[:8],16))
        self.chart=chart;self.duration=chart['duration'];self.offset=chart['offset'];self.round=Judgement(chart)
        self.keys_text=('D','F','J') if chart['lanes']==3 else ('D','F','J','K')
        self.keys=tuple(getattr(Qt,'Key_'+key) for key in self.keys_text)
        configured=mod.store.preference('keys:'+str(chart['lanes']),None)
        if isinstance(configured,list) and len(configured)==chart['lanes'] and len(set(configured))==len(configured) and all(type(x) is int and 32<=x<=90 for x in configured):
            self.keys=tuple(configured);self.keys_text=tuple(QKeySequence(key).toString() for key in configured)
        self.session=uuid.uuid4().hex;self.elapsed=0.;self.started=None
        self.requested=False;self.finished=False;self.paused=False;self.resume_keys=set();self.resume_wait=False
        self.flash=0.;self.flash_lane=1;self.feedback='';self.last_elapsed=0.;self.last_advance=time.monotonic();self.last_actor=0
        self.transport=ClipPlayer(mod,self)
        self.transport.started.connect(self.audio_started)
        self.transport.finished.connect(self.finish)
        self.transport.failed.connect(self.failed)
        self.effect=None;self.tap_bytes=None;self.tap_level=None
        box=QVBoxLayout(self);box.setContentsMargins(15,12,15,12);box.setSpacing(8)
        self.label=QLabel(self.title+' · '+('节拍练习谱' if chart['practice'] else '歌曲拍点谱'));self.label.setObjectName('sectionTitle')
        self.label.setTextFormat(Qt.PlainText);self.label.setWordWrap(True);box.addWidget(self.label)
        self.stage=Stage(self);box.addWidget(self.stage,1)
        self.score=QLabel('薄荷色单点轻按，金色长条按住到尾端。');self.score.setObjectName('entryTitle');box.addWidget(self.score)
        settings=QWidget();options=QHBoxLayout(settings);options.setContentsMargins(0,0,0,0);settings.hide()
        self.sound=QCheckBox('判定音');self.sound.setChecked(True);options.addWidget(self.sound)
        self.effects=QCheckBox('舞台光效');self.effects.setChecked(True);options.addWidget(self.effects)
        options.addWidget(QLabel('可见提前量'))
        self.speed=QSpinBox();self.speed.setRange(800,4000);self.speed.setValue(2000);self.speed.setSuffix(' ms');options.addWidget(self.speed)
        options.addWidget(QLabel('输入偏移'))
        self.offset_control=QSpinBox();self.offset_control.setRange(-500,500);self.offset_control.setSuffix(' ms')
        self.offset_control.setValue(mod.store.preference('input_offset',0) if hasattr(mod.store,'preference') else 0)
        options.addWidget(self.offset_control);box.addWidget(settings)
        row=QHBoxLayout();self.start_button=QPushButton('开始演出');self.start_button.setObjectName('primary');self.start_button.clicked.connect(self.start);row.addWidget(self.start_button)
        self.pause_button=QPushButton('暂停 / 继续');self.pause_button.setEnabled(False);self.pause_button.clicked.connect(self.toggle_pause);row.addWidget(self.pause_button)
        self.favorite=QPushButton('收藏这份谱');self.favorite.clicked.connect(self.save_chart);row.addWidget(self.favorite);box.addLayout(row)
        self.key_button=QPushButton('调整按键');self.key_button.clicked.connect(self.configure_keys);options.addWidget(self.key_button)
        row.addStretch();self.settings_button=QPushButton('游玩设置');self.settings_button.setCheckable(True);self.settings_button.toggled.connect(settings.setVisible);row.addWidget(self.settings_button)
        self.timer=QTimer(self);self.timer.setInterval(16);self.timer.timeout.connect(self.update_game)
        self.countdown=QTimer(self);self.countdown.setSingleShot(True);self.countdown.timeout.connect(self.resume)

    def now(self):
        if self.started is None:return 0.
        return self.transport.clock() if self.source else time.monotonic()-self.started

    def save_chart(self):
        try:self.mod.store.save_chart(self.chart,True);self.favorite.setText('已收藏，可从演出页重玩')
        except Exception:self.label.setText('谱面保存失败，请检查磁盘空间。')

    def start(self):
        if self.requested or self.finished or not self.mod.active:return
        if not self.source and not self.transport.claim():
            self.label.setText('另一项互动正在播放，请先结束那项互动，再点开始。');return
        self.requested=True;self.start_button.setEnabled(False);self.offset_control.setEnabled(False)
        self.key_button.setEnabled(False)
        self.mod.store.configure('input_offset',self.offset_control.value())
        self.last_advance=time.monotonic()
        if self.source:
            self.label.setText('正在准备演出片段…')
            self.transport.play(self.source,self.offset,self.duration)
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

    def audio_started(self):
        if self.finished or not self.requested or not self.mod.active:return
        self.label.setText(self.title)
        self.started=self.last_advance=time.monotonic();self.timer.start();self.pause_button.setEnabled(True)
        self.mod.services.act('sing')

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
        self.paused=True;self.resume_keys.clear();self.stage.update()
        if self.source:self.transport.toggle_pause()
        self.stop_tap()

    def resume(self):
        self.resume_wait=False
        if not self.paused or self.finished or not self.mod.active:return
        self.round.held=set(self.resume_keys);self.round.rearm();self.paused=False
        self.started=time.monotonic()-self.elapsed;self.last_advance=time.monotonic()
        if self.source:self.transport.toggle_pause()
        self.label.setText(self.title);self.stage.setFocus()

    def event(self,event):
        if event.type()==QEvent.WindowDeactivate and hasattr(self,'paused'):
            self.countdown.stop();self.resume_wait=False;self.pause()
        return super().event(event)

    def play_tap(self):
        if not self.sound.isChecked():return
        import sys
        level = self.mod.services.snapshot().get('volume',.5)
        if level <= 0:return
        try:
            if sys.platform == 'win32':
                # PlaySound uses the Windows mixer directly. Constructing the first
                # Qt sound effect here can stall the GUI for an entire musical bar.
                import ctypes
                if self.tap_bytes is None or self.tap_level != level:
                    self.stop_tap()
                    self.tap_bytes = ctypes.create_string_buffer(self.tap_wave(.3*level))
                    self.tap_level = level
                ctypes.windll.winmm.PlaySoundW(self.tap_bytes, None, 0x0007)  # MEMORY | NODEFAULT | ASYNC
            else:
                from PySide6.QtMultimedia import QSoundEffect
                if self.effect is None:
                    path=self.mod.context.data_dir/'tap.wav'
                    if not path.exists():path.write_bytes(self.tap_wave(1.))
                    self.effect=QSoundEffect(self);self.effect.setSource(QUrl.fromLocalFile(str(path)))
                self.effect.setVolume(.3*level);self.effect.play()
        except (OSError,ValueError):return

    @staticmethod
    def tap_wave(gain):
        import io,struct,wave
        buffer=io.BytesIO()
        samples=[int(8000*gain*math.exp(-i/600)*math.sin(math.tau*880*i/22050)) for i in range(1764)]
        with wave.open(buffer,'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(22050);out.writeframes(struct.pack('<1764h',*samples))
        return buffer.getvalue()

    def stop_tap(self):
        if self.tap_bytes is not None:
            import ctypes
            ctypes.windll.winmm.PlaySoundW(None,None,0)
            self.tap_bytes=None
        if self.effect:self.effect.stop()

    def update_game(self):
        if self.finished or self.started is None:return
        if not self.mod.active:self.close();return
        if not self.transport.valid():self.failed('本次互动已结束。');return
        if self.paused:return
        self.elapsed=self.now()
        if self.elapsed>self.last_elapsed:
            self.last_advance=time.monotonic();self.last_elapsed=self.elapsed
        elif time.monotonic()-self.last_advance>20:self.failed('音频播放超时，请检查输出设备。');return
        self.round.advance(self.elapsed+self.offset_control.value()/1000);self.stage.update()
        score_line = f'得分 {self.round.score:,}   ·   连击 {self.round.combo}   ·   长条 {self.round.holds}   ·   剩余 {max(0,int(self.duration-self.elapsed))} 秒'
        if score_line != self.score.text():self.score.setText(score_line)
        if time.monotonic()-self.last_actor>3:
            self.last_actor=time.monotonic();self.mod.services.act('sing')
        if not self.source and self.elapsed>=self.duration:self.finish()

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
        self.timer.stop();self.countdown.stop();self.pause_button.setEnabled(False)
        self.transport.close();self.stop_tap()

    def failed(self,message):
        if self.finished:return
        self.finished=True;self.release_audio();self.start_button.setText('重试这份谱');self.start_button.setEnabled(True)
        self.start_button.clicked.disconnect();self.start_button.clicked.connect(self.retry)
        self.label.setText(message)

    def closeEvent(self,event):
        self.finished=True;self.release_audio();super().closeEvent(event)

    def done(self,result):
        self.finished=True;self.release_audio();super().done(result)
