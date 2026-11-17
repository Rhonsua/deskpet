"""Metadata-backed guessing and three-song shows. No online answer generation."""
import hashlib
import random
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QRectF,QEvent
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QPushButton,QComboBox,QFileDialog,QProgressBar,QWidget,QFrame,QHBoxLayout
from PySide6.QtGui import QPainter,QColor,QLinearGradient,QFont,QPixmap,QPalette
from .playback import ClipPlayer

# A scan may be inside a slow filesystem or metadata call when its dialog
# closes. Keep its unparented QThread alive until it actually finishes.
_scanners=set()
_shutdown_connected=False

def _shutdown_scanners():
    # Application teardown must not destroy a running QThread. Unlike closing
    # a single dialog, process shutdown is the final opportunity to join it.
    for scanner in tuple(_scanners):scanner.requestInterruption()
    for scanner in tuple(_scanners):scanner.wait()

class Scanner(QThread):
    scanned=Signal(list)
    def __init__(self,paths,parent):super().__init__(parent);self.paths=paths
    def run(self):
        from mutagen import File
        result=[];seen=set()
        for item in self.paths[:512]:
            if self.isInterruptionRequested():return
            path=Path(item)
            if str(path).startswith('\\\\') or not path.is_file():continue
            try:
                audio=File(path,easy=True)
                if audio is None or not audio.info or audio.info.length<15:continue
                tags=audio.tags or {};title=str(tags.get('title',[path.stem])[0]).strip()
                title=re.sub(r'[_\s]+',' ',title)
                key=title.casefold()
                if len(title)<2 or re.fullmatch(r'[\d\W_]+',title) or key in seen:continue
                seen.add(key);result.append(dict(path=str(path),title=title[:160],duration=float(audio.info.length)))
            except Exception:continue
        self.scanned.emit(result)


class LibraryDialog(QDialog):
    def __init__(self,mod,title,parent=None):
        super().__init__(parent);self.mod=mod;self.setWindowTitle(title);self.setAttribute(Qt.WA_DeleteOnClose)
        dark=QApplication.palette().color(QPalette.Window).lightness()<128
        bg,card,ink,muted,border,button,accent=('#142733','#203b49','#edf6f8','#bed2d9','#42616d','#294a58','#83cbe0') if dark else ('#f2f8fb','#fffdf9','#243e4d','#55717d','#c8dfe8','#e4f1f7','#287c99')
        self.setStyleSheet(f"""QDialog {{background:{bg};color:{ink};font:10pt 'Microsoft YaHei UI';}}
            QFrame#section {{background:{card};border:1px solid {border};border-radius:12px;}}
            QLabel {{color:{ink};background:transparent;}} QLabel#muted {{color:{muted};}}
            QPushButton,QComboBox {{padding:7px 12px;border:1px solid {border};border-radius:7px;background:{button};color:{ink};}}
            QPushButton:hover {{border-color:{accent};}} QPushButton:disabled {{color:{muted};}}
            QPushButton#primary {{background:{accent};color:{'#102c39' if dark else 'white'};font-weight:bold;}}
            QComboBox QAbstractItemView {{background:{card};color:{ink};selection-background-color:{button};selection-color:{ink};}}
            QProgressBar {{background:{button};border:0;border-radius:4px;height:8px;color:{ink};}} QProgressBar::chunk {{background:{accent};border-radius:4px;}}""")
        self.resize(720,680);self.box=QVBoxLayout(self);self.box.setContentsMargins(20,18,20,18);self.box.setSpacing(10)
        self.header=QLabel(title.replace('天依 · ',''));self.header.setStyleSheet('font-size:17pt;font-weight:bold;');self.box.addWidget(self.header)
        self.library_card=QFrame();self.library_card.setObjectName('section');library_layout=QHBoxLayout(self.library_card);library_layout.setContentsMargins(14,10,14,10)
        self.label=QLabel('读取已有歌曲信息…');self.label.setWordWrap(True);self.label.setTextFormat(Qt.PlainText);library_layout.addWidget(self.label,1)
        self.tracks=[];self.scanner=None;self.closed=False
        self.add=QPushButton('补充歌曲');self.add.clicked.connect(self.choose);library_layout.addWidget(self.add);self.box.addWidget(self.library_card)
        self.player=ClipPlayer(mod,self);self.player.failed.connect(self.error)
        QTimer.singleShot(0,self.scan)

    def choose(self):
        files,_=QFileDialog.getOpenFileNames(self,'选择本地歌曲','','音乐 (*.mp3 *.wav *.flac *.ogg *.m4a)')
        if files:
            old=self.mod.store.preference('extra_tracks',[])
            self.mod.store.configure('extra_tracks',list(dict.fromkeys(old+files))[:512]);self.scan()

    def scan(self):
        global _shutdown_connected
        if self.closed or not self.mod.active:return
        if self.scanner and self.scanner.isRunning():return
        if not _shutdown_connected:
            QApplication.instance().aboutToQuit.connect(_shutdown_scanners)
            _shutdown_connected=True
        paths=[x['path'] for x in self.mod.services.library()]+self.mod.store.preference('extra_tracks',[])
        self.scanner=Scanner(list(dict.fromkeys(paths)),None)
        _scanners.add(self.scanner)
        self.scanner.finished.connect(self._scanner_finished)
        self.scanner.finished.connect(self.scanner.deleteLater)
        self.scanner.finished.connect(lambda scanner=self.scanner:_scanners.discard(scanner))
        self.scanner.scanned.connect(self._scan_ready);self.scanner.start()

    def _scan_ready(self,tracks):
        if not self.closed and self.mod.active:self.ready(tracks)

    def _scanner_finished(self):
        if self.scanner is self.sender():self.scanner=None

    def ready(self,tracks):
        if self.closed or not self.mod.active:return
        self.tracks=tracks;self.label.setText(f'找到 {len(tracks)} 首可用本地歌曲。')

    def error(self,message):self.label.setText(message)

    def closeEvent(self,e):
        self.closed=True;self.player.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.requestInterruption()
        super().closeEvent(e)


class ShowStage(QWidget):
    def __init__(self,show):
        super().__init__(show);self.show=show;self.elapsed=0.;self.phase=0.;self.theme=show.mod.store.preference('theme','');self.stage_number=show.mod.store.stage;self.setMinimumHeight(230)
        assets=Path(__file__).parent/'assets'
        self.portrait=QPixmap(str(assets/'tianyi-stage.webp'))
        self.singing=[QPixmap(str(assets/f'tianyi-sing-{direction}.webp')) for direction in ('front','left','front','right')]
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.animate)
    def animate(self):
        self.phase+=.1;self.update()
    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
    def paintEvent(self,event):
        import math
        from .stage_art import paint_stage
        show=self.show;stage=self.stage_number;theme=self.theme
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setRenderHint(QPainter.SmoothPixmapTransform)
        paint_stage(p,QRectF(self.rect()),theme,stage,self.phase,performance=True)
        clip_elapsed=max(0.,self.elapsed-show.index*30) if show.index>=0 else 0
        entrance=min(1.,clip_elapsed);exit_fade=min(1.,max(0.,30-clip_elapsed))
        opacity=min(entrance,exit_fade) if show.program and not show.complete else 1.
        shift=(1-entrance)*26-(1-exit_fade)*26 if show.program and not show.complete else 0
        def draw_person(pix,alpha):
            if pix.isNull() or alpha<=0:return
            target_h=min(self.height()*.83,340);target_w=target_h*pix.width()/pix.height()
            x=self.width()*.27-target_w/2+math.sin(self.phase)*2+shift;y=self.height()-target_h-10+math.sin(self.phase*1.2)*1.5
            p.save();p.setOpacity(alpha);p.drawPixmap(QRectF(x,y,target_w,target_h),pix,QRectF(pix.rect()));p.restore()
        if show.program and not show.complete:
            index=int(clip_elapsed/3.5)%4;mix=min(1.,(clip_elapsed%3.5)/.2)
            current=self.singing[index] if not self.singing[index].isNull() else self.portrait
            previous=self.singing[(index-1)%4] if not self.singing[(index-1)%4].isNull() else self.portrait
            if clip_elapsed>=3.5 and mix<1:draw_person(previous,opacity*(1-mix))
            draw_person(current,opacity*(mix if clip_elapsed>=3.5 else 1))
        else:draw_person(self.portrait,1.)
        p.setPen(QColor('#f5fbfc'));p.setFont(QFont(self.font().family(),13,QFont.Bold))
        caption='三首歌 · 每首试听 30 秒'
        if show.program and 0<=show.index<len(show.program):caption=f'第 {show.index+1} 幕\n\n'+show.program[show.index]['title']
        if show.complete:caption='演出结束，谢谢陪伴'
        if show.program and 0<=show.index<len(show.program) and not show.complete:
            clip_elapsed=self.elapsed-show.index*30;fade=min(1.,max(0.,clip_elapsed),max(0.,30-clip_elapsed))
            p.setOpacity(fade);p.translate((1-fade)*16,0)
        p.drawText(QRectF(self.width()*.48,25,self.width()*.46,self.height()-50),Qt.AlignCenter|Qt.TextWordWrap,caption);p.end()


class AnswerButton(QPushButton):
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumHeight(50);layout=QVBoxLayout(self);layout.setContentsMargins(8,5,8,5)
        self.caption=QLabel();self.caption.setStyleSheet('font-size:11pt;');self.caption.setTextFormat(Qt.PlainText);self.caption.setWordWrap(True);self.caption.setAlignment(Qt.AlignCenter);self.caption.setAttribute(Qt.WA_TransparentForMouseEvents);layout.addWidget(self.caption)
    def setText(self,text):
        super().setText('');self.caption.setText(text);self.setToolTip(text);self.setAccessibleName(text)


class GuessGame(LibraryDialog):
    def __init__(self,mod,parent=None):
        super().__init__(mod,'天依 · 猜歌挑战',parent);self.resize(680,520)
        self.start_button=QPushButton('开始三题猜歌');self.start_button.setObjectName('primary');self.start_button.setEnabled(False);self.start_button.clicked.connect(self.start_game);self.box.addWidget(self.start_button,0,Qt.AlignLeft)
        panel=QFrame();panel.setObjectName('section');panel_box=QVBoxLayout(panel);panel_box.setContentsMargins(16,14,16,14);panel_box.setSpacing(8)
        self.question_title=QLabel('听一段旋律，选出歌名');self.question_title.setStyleSheet('font-size:12pt;font-weight:bold;');panel_box.addWidget(self.question_title)
        self.question_progress=QProgressBar();self.question_progress.setRange(0,3);self.question_progress.setTextVisible(False);panel_box.addWidget(self.question_progress)
        self.answers=[]
        for i in range(3):
            button=AnswerButton();button.setText('—');button.setEnabled(False);button.clicked.connect(lambda checked=False,n=i:self.answer(n));panel_box.addWidget(button);self.answers.append(button)
        row=QHBoxLayout();self.relisten=QPushButton('再听一次');self.relisten.setEnabled(False);self.relisten.clicked.connect(self.replay_clip);row.addWidget(self.relisten)
        self.next_button=QPushButton('下一题');self.next_button.clicked.connect(self.next_question);self.next_button.setEnabled(False);row.addWidget(self.next_button);row.addStretch();panel_box.addLayout(row);self.box.addWidget(panel);self.box.addStretch()
        self.player.finished.connect(self.clip_done);self.index=0;self.correct=0;self.questions=[];self.answered=False;self.completed=False

    def ready(self,tracks):
        super().ready(tracks)
        self.start_button.setEnabled(len(tracks)>=3 and not self.questions)
        if len(tracks)<3:self.label.setText('猜歌需要至少三首歌名不同、可读取的歌曲，可以补充本地歌曲。')

    def start_game(self):
        if len(self.tracks)<3 or self.questions:return
        self.questions=random.sample(self.tracks,3);self.session=uuid.uuid4().hex
        self.start_button.hide();self.add.setEnabled(False);self.next_question()

    def next_question(self):
        if self.closed or self.completed or not self.questions or (hasattr(self,'current') and not self.answered):return
        if self.index>=3:self.complete();return
        self.current=self.questions[self.index];self.options=random.sample([x for x in self.tracks if x!=self.current],2)+[self.current]
        random.shuffle(self.options);self.answered=False;self.clip_ready=False;self.next_button.setEnabled(False)
        for button,track in zip(self.answers,self.options):button.setText(track['title']);button.setEnabled(False)
        self.question_title.setText(f'第 {self.index+1} / 3 题 · 正在试听');self.question_progress.setValue(self.index);self.relisten.setEnabled(False);self.label.setText('听完这段旋律后，就可以选择歌名。')
        self.clip_offset=min(self.current['duration']-9,self.current['duration']*random.uniform(.2,.65))
        if not self.player.play(self.current['path'],self.clip_offset,8):self.error('播放不可用，请关闭后重试。')

    def replay_clip(self):
        if self.answered or not self.clip_ready or self.completed:return
        self.clip_ready=False;self.relisten.setEnabled(False)
        for button in self.answers:button.setEnabled(False)
        self.question_title.setText(f'第 {self.index+1} / 3 题 · 正在重听')
        if not self.player.play(self.current['path'],self.clip_offset,8):self.error('播放不可用，请关闭后重试。')

    def clip_done(self):
        if self.closed or self.answered or self.completed or not hasattr(self,'current') or self.index>=len(self.questions):return
        self.clip_ready=True;self.relisten.setEnabled(True);self.question_title.setText(f'第 {self.index+1} / 3 题 · 选择歌名')
        for button in self.answers:button.setEnabled(True)
        self.label.setText(f'第 {self.index+1} / 3 题 · 这段是哪首歌？')

    def answer(self,n):
        if self.answered or not self.clip_ready or self.completed:return
        self.answered=True;self.relisten.setEnabled(False);self.question_title.setText(f'第 {self.index+1} / 3 题 · 本题反馈')
        for button in self.answers:button.setEnabled(False)
        if self.options[n]==self.current:
            self.correct+=1;self.mod.services.act('happy');self.label.setText('答对啦，是《'+self.current['title']+'》！')
        else:
            hint=''
            lrc=Path(self.current['path']).with_suffix('.lrc')
            try:
                if lrc.is_file() and lrc.stat().st_size<500000:
                    lines=[re.sub(r'\[[^]]*\]','',x).strip() for x in lrc.read_text(encoding='utf-8-sig',errors='replace').splitlines() if re.match(r'\[\d+:\d+',x)]
                    hint=next((x for x in lines if x),'')[:100]
            except OSError:pass
            self.label.setText('是《'+self.current['title']+'》。没关系，下次就熟悉啦。'+('\n歌词小提示：'+hint if hint else ''))
        self.index+=1;self.next_button.setText('完成挑战' if self.index==3 else '下一题');self.next_button.setEnabled(True)

    def complete(self):
        if self.completed:return
        self.completed=True;self.next_button.setEnabled(False);self.question_progress.setValue(3);self.question_title.setText('挑战完成')
        judge=SimpleNamespace(score=round(self.correct/3*1000000),best=self.correct,perfect=self.correct,good=0,misses=3-self.correct,holds=0)
        before=self.mod.store.stage
        self.mod.store.complete_round(self.session,'quiz:'+self.session,'三首真实歌曲',judge,kind='quiz')
        if self.correct==3:
            with self.mod.store.db:self.mod.store.card('quiz:three','三首都认出来啦','这一轮歌曲：'+'、'.join(t['title'] for t in self.questions))
        self.mod.after_growth(before);self.label.setText(f'完成啦，认出了 {self.correct} / 3 首。谢谢你一起听歌。')


class WeeklyShow(LibraryDialog):
    def __init__(self,mod,parent=None):
        super().__init__(mod,'天依 · 三曲小演出',parent)
        playlist=QFrame();self.playlist_panel=playlist;playlist.setObjectName('section');playlist_box=QVBoxLayout(playlist);playlist_box.setContentsMargins(14,10,14,10)
        title=QLabel('节目单 · 选择三首不同的歌');title.setStyleSheet('font-weight:bold;font-size:12pt;');playlist_box.addWidget(title)
        self.selectors=[]
        for i in range(3):
            row=QHBoxLayout();row.addWidget(QLabel(f'第 {i+1} 首'));combo=QComboBox();row.addWidget(combo,1);playlist_box.addLayout(row);self.selectors.append(combo)
        row=QHBoxLayout();row.addWidget(QLabel('谢幕动作'));self.encore=QComboBox()
        for name,key in [('挥手谢幕','wave'),('转身谢幕','turn'),('开心谢幕','happy')]:self.encore.addItem(name,key)
        row.addWidget(self.encore,1);playlist_box.addLayout(row);self.box.addWidget(playlist)
        self.program_line=QLabel();self.program_line.setTextFormat(Qt.PlainText);self.program_line.setWordWrap(True);self.program_line.hide();self.box.addWidget(self.program_line)
        self.stage=ShowStage(self);self.box.addWidget(self.stage,1)
        self.finale=QLabel();self.finale.setTextFormat(Qt.PlainText);self.finale.setWordWrap(True);self.finale.setStyleSheet('font-weight:bold;padding:10px;');self.finale.hide();self.box.addWidget(self.finale)
        self.progress=QProgressBar();self.progress.setRange(0,90);self.progress.setTextVisible(False);self.box.addWidget(self.progress)
        row=QHBoxLayout();self.start_button=QPushButton('开始三曲演出');self.start_button.setObjectName('primary');self.start_button.setEnabled(False);self.start_button.clicked.connect(self.start_show);row.addWidget(self.start_button)
        self.pause_button=QPushButton('暂停演出');self.pause_button.setEnabled(False);self.pause_button.clicked.connect(self.pause);row.addWidget(self.pause_button)
        self.open_album=QPushButton('打开纪念册');self.open_album.hide();self.open_album.clicked.connect(lambda:self.mod.open(2));row.addWidget(self.open_album);row.addStretch();self.box.addLayout(row)
        self.player.finished.connect(self.next_song);self.player.progress.connect(self.update_progress)
        self.program=[];self.index=-1;self.last_action=0.;self.failed=False;self.complete=False

    def ready(self,tracks):
        tracks=[x for x in tracks if x['duration']>=35]
        super().ready(tracks)
        for i,combo in enumerate(self.selectors):
            combo.clear()
            for track in tracks:combo.addItem(track['title'],track)
            combo.setCurrentIndex(min(i,len(tracks)-1))
        self.start_button.setEnabled(len(tracks)>=3)
        self.label.setText('选择三首歌，每首演出 30 秒，使用当前选定的舞台装饰。' if len(tracks)>=3 else '需要三首至少 35 秒的本地歌曲。')

    def start_show(self):
        if self.program:return
        program=[combo.currentData() for combo in self.selectors]
        if len({x['path'] for x in program if x})!=3:self.label.setText('请选择三首不同的歌曲。');return
        self.stage.theme=self.mod.store.preference('theme','');self.stage.stage_number=self.mod.store.stage
        self.stage.elapsed=0;self.playlist_panel.hide();self.program_line.setText('节目单  ·  '+'  /  '.join(x['title'] for x in program));self.program_line.setToolTip('\n'.join(x['title'] for x in program));self.program_line.show()
        self.program=program;self.session=uuid.uuid4().hex;self.start_button.hide();self.add.setEnabled(False)
        for combo in self.selectors:combo.setEnabled(False)
        self.encore.setEnabled(False);self.pause_button.setEnabled(True)
        self.next_song()

    def pause(self):
        self.player.toggle_pause();self.pause_button.setText('继续演出' if self.player.paused else '暂停演出')
        if self.player.paused:self.stage.timer.stop()
        elif self.isVisible() and not self.isMinimized() and self.player.live and self.player.loaded:self.stage.timer.start()

    def next_song(self):
        if self.closed or self.failed or self.complete:return
        previous=self.index
        self.index+=1
        if self.index>=3:
            self.complete=True;self.progress.setValue(90);self.mod.store.record_show(self.session,self.program)
            self.pause_button.hide();self.stage.timer.stop();self.open_album.show();self.finale.setText('演出纪念 · 三段旋律\n'+'\n'.join(f'{i+1}. {track["title"]}' for i,track in enumerate(self.program)));self.finale.show();self.stage.update()
            self.mod.services.act(self.encore.currentData());self.mod.refresh();self.label.setText('三曲演出完成！节目单已经收进纪念册，可导出纪念卡。');return
        self.stage.elapsed=self.index*30
        track=self.program[self.index];self.label.setText((f'第 {previous+1} 首结束 · ' if previous>=0 else '')+f'第 {self.index+1} / 3 首登场 · 《{track["title"]}》');self.stage.update()
        offset=min(track['duration']-31,track['duration']*.3)
        if not self.player.play(track['path'],offset,30):
            self.error('暂时不能播放，请关闭后重试。');return
        self.mod.services.act('sing')

    def update_progress(self,elapsed):
        if self.closed or self.failed or self.complete or not 0<=self.index<len(self.program):return
        self.stage.elapsed=self.index*30+elapsed
        if self.isVisible() and not self.isMinimized() and self.player.live and self.player.loaded and not self.player.paused and not self.stage.timer.isActive():self.stage.timer.start()
        self.stage.update()
        if elapsed>=1:
            text=f'正在演出 {self.index+1} / 3 · 《{self.program[self.index]["title"]}》'
            if self.label.text()!=text:self.label.setText(text)
        self.progress.setValue(min(90,round(self.index*30+elapsed)))
        volume=self.mod.services.snapshot().get('volume',.5)
        self.player.audio.setVolume(volume*min(1.,max(0.,elapsed),max(0.,30-elapsed)))
        import time
        if time.monotonic()-self.last_action>3:self.last_action=time.monotonic();self.mod.services.act('sing')

    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'stage') and self.player.live and self.player.loaded and not self.player.paused and not self.isMinimized():self.stage.timer.start()

    def hideEvent(self,event):
        if hasattr(self,'stage'):self.stage.timer.stop()
        super().hideEvent(event)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:
            if self.isMinimized():self.stage.timer.stop()
            elif self.isVisible() and self.player.live and self.player.loaded and not self.player.paused:self.stage.timer.start()

    def closeEvent(self,event):
        self.stage.timer.stop();super().closeEvent(event)

    def error(self,message):
        self.failed=True;self.stage.timer.stop();self.start_button.setEnabled(False);self.pause_button.setEnabled(False);self.player.stop();self.label.setText(message+' 未记为完成演出。')
