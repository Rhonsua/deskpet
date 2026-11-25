"""Metadata-backed guessing and three-song shows. No online answer generation."""
import math
import random
import re
import uuid
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import Qt,QThread,Signal,QTimer,QRectF,QEvent,QStringListModel
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QPushButton,QComboBox,QFileDialog,QProgressBar,QWidget,QFrame,QHBoxLayout,QSizePolicy
from PySide6.QtGui import QPainter,QColor,QFont,QKeySequence,QFontMetrics,QTextLayout,QTextOption
from .playback import ClipPlayer
from .studio import IllustratedHeader, activity_style, dark_theme, set_role
from .stage_art import PerformanceBackdrop, paint_lights, scene_name, stage_image
from .scrapbook import activity_images

# A scan may be inside a slow filesystem or metadata call when its dialog
# closes. Keep its unparented QThread alive until it actually finishes.
_scanners=set()
_shutdown_connected=False

def _shutdown_scanners():
    # Application teardown must not destroy a running QThread. Unlike closing
    # a single dialog, process shutdown is the final opportunity to join it.
    for scanner in tuple(_scanners):scanner.requestInterruption()
    for scanner in tuple(_scanners):scanner.wait()

@lru_cache(maxsize=512)
def _song_metadata(path, size, modified):
    from mutagen import File
    audio = File(path, easy=True)
    if audio is None or not audio.info:
        return None
    duration = float(audio.info.length)
    if not math.isfinite(duration) or duration <= 0:
        return None
    title = str(((audio.tags or {}).get('title') or [path.stem])[0])
    title = re.sub(r'[_\s]+', ' ', title).strip() or path.stem
    return title[:160], duration


def _timecode(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


class Scanner(QThread):
    scanned=Signal(list)
    def __init__(self,paths,parent):super().__init__(parent);self.paths=paths
    def run(self):
        result=[]
        for path in dict.fromkeys(Path(item) for item in self.paths[:512]):
            if self.isInterruptionRequested():return
            if str(path).startswith('\\\\'):continue
            try:
                stat = path.stat()
                metadata = _song_metadata(path, stat.st_size, stat.st_mtime_ns)
                if not metadata:continue
                title, duration = metadata
                result.append(dict(path=str(path),title=title,duration=duration))
            except Exception:continue
        self.scanned.emit(result)


class LibraryDialog(QDialog):
    def __init__(self, mod, title, detail, illustration, parent=None):
        super().__init__(parent)
        self.mod = mod
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(activity_style(dark_theme()))
        self.resize(720, 680)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(16, 14, 16, 14)
        self.box.setSpacing(9)
        self.header = IllustratedHeader(title.removeprefix('天依 · '), detail, illustration)
        self.box.addWidget(self.header)
        self.library_card=QFrame();self.library_card.setObjectName('section');library_layout=QHBoxLayout(self.library_card);library_layout.setContentsMargins(14,10,14,10)
        self.label=QLabel('读取已有歌曲信息…');self.label.setWordWrap(True);self.label.setTextFormat(Qt.PlainText);library_layout.addWidget(self.label,1)
        self.tracks=[];self.scanner=None;self.closed=False;self.rescan_requested=False
        self.add=QPushButton('补充歌曲');self.add.clicked.connect(self.choose);library_layout.addWidget(self.add);self.box.addWidget(self.library_card)
        self.player=ClipPlayer(mod,self);self.player.failed.connect(self.error)
        QTimer.singleShot(0,self,self.scan)

    def choose(self):
        files,_=QFileDialog.getOpenFileNames(self,'选择本地歌曲','','音乐 (*.mp3 *.wav *.flac *.ogg *.m4a)')
        if files:
            old=self.mod.store.preference('extra_tracks',[])
            self.mod.store.configure('extra_tracks',list(dict.fromkeys(files+old))[:512])
            self.rescan()

    def rescan(self):
        if self.scanner and self.scanner.isRunning():
            self.rescan_requested=True
            self.scanner.requestInterruption()
        else:
            self.rescan_requested=False
            self.scan()

    def scan(self):
        global _shutdown_connected
        if self.closed or not self.mod.active:return
        if self.scanner and self.scanner.isRunning():return
        if not _shutdown_connected:
            QApplication.instance().aboutToQuit.connect(_shutdown_scanners)
            _shutdown_connected=True
        paths=self.mod.store.preference('extra_tracks',[])+[x['path'] for x in self.mod.services.library()]
        self.scanner=Scanner(list(dict.fromkeys(paths)),None)
        _scanners.add(self.scanner)
        self.scanner.finished.connect(self._scanner_finished)
        self.scanner.finished.connect(self.scanner.deleteLater)
        self.scanner.finished.connect(lambda scanner=self.scanner:_scanners.discard(scanner))
        self.scanner.scanned.connect(self._scan_ready);self.scanner.start()

    def _scan_ready(self,tracks):
        if not self.closed and self.mod.active and not self.rescan_requested:self.ready(tracks)

    def _scanner_finished(self):
        if self.scanner is self.sender():
            self.scanner=None
            if self.rescan_requested and not self.closed:
                self.rescan_requested=False
                self.scan()

    def ready(self,tracks):
        if self.closed or not self.mod.active:return
        self.tracks=tracks;self.label.setText(f'找到 {len(tracks)} 首可用本地歌曲。')

    def error(self,message):self.library_card.show();self.label.setText(message)

    def _shutdown(self):
        if self.closed:return
        self.closed=True;self.player.close()
        if self.scanner and self.scanner.isRunning():
            self.scanner.requestInterruption()

    def closeEvent(self,e):
        self._shutdown()
        super().closeEvent(e)

    def done(self,result):
        self._shutdown()
        super().done(result)


class ShowStage(QWidget):
    def __init__(self,show):
        super().__init__(show);self.show=show;self.elapsed=0.;self.phase=0.;self.theme=show.mod.store.preference('theme','');self.stage_number=show.mod.store.stage;self.setMinimumHeight(230)
        self.backdrop = PerformanceBackdrop()
        activity_images().ready.connect(self.update)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.animate)
    def animate(self):
        self.phase+=.1;self.update()
    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)
    def paintEvent(self,event):
        show=self.show;stage=self.stage_number;theme=self.theme
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing);p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.backdrop.draw(p, self, theme, stage)
        live = bool(show.program and 0 <= show.index < len(show.program) and show.player.loaded and not show.failed and not show.complete)
        if live:
            paint_lights(p, self.rect(), scene_name(theme, stage), self.phase)
        clip_elapsed = self.elapsed
        opacity, shift = 1., 0.
        if live:
            duration = show.program[show.index]['duration']
            transition = min(1., duration / 4)
            entrance = min(1., clip_elapsed / transition)
            remaining = duration - clip_elapsed
            exit_fade = min(1., remaining / transition) if remaining >= 0 else 1.
            opacity = min(entrance, exit_fade)
            shift = (exit_fade - entrance) * 26
        def draw_person(pix,alpha):
            if pix.isNull() or alpha<=0:return
            target_h=min(self.height()*.83,340);target_w=target_h*pix.width()/pix.height()
            x=self.width()*.27-target_w/2+math.sin(self.phase)*2+shift;y=self.height()-target_h-10+math.sin(self.phase*1.2)*1.5
            p.save();p.setOpacity(alpha);p.drawPixmap(QRectF(x,y,target_w,target_h),pix,QRectF(pix.rect()));p.restore()
        portrait = stage_image('tianyi-stage')
        if live:
            index=int(clip_elapsed/3.5)%4;mix=min(1.,(clip_elapsed%3.5)/.2)
            poses = ('front','left','front','right')
            current = stage_image('tianyi-sing-' + poses[index])
            if clip_elapsed>=3.5 and mix<1:
                previous = stage_image('tianyi-sing-' + poses[index-1])
                draw_person(portrait if previous.isNull() else previous,opacity*(1-mix))
            draw_person(portrait if current.isNull() else current,opacity*(mix if clip_elapsed>=3.5 else 1))
        else:draw_person(portrait,1.)
        if live:
            p.setOpacity(opacity)
            p.translate((1-opacity)*16, 0)
        title = show.program[show.index]['title'] if live else ('谢谢你来听歌' if show.complete else '天依的三曲小演出')
        font = QFont(self.font().family(), 15, QFont.Bold)
        metrics = QFontMetrics(font)
        width = self.width()*.46
        text_width = max(10, round(width)-28)
        flags = Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWrapAnywhere
        bounds = metrics.boundingRect(0, 0, text_width, 200, flags, title)
        max_lines = 2 if self.height()<310 else 3
        title_height = min(max_lines*metrics.lineSpacing()+3, max(metrics.height(), bounds.height()))
        if bounds.height() > title_height:
            title = metrics.elidedText(title, Qt.ElideRight, max(1, text_width-metrics.averageCharWidth())*max_lines)
        height = title_height + (64 if live else 44)
        right = QRectF(self.width()*.48, (self.height()-height)*.53, width, height)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(16, 31, 45, 226))
        p.drawRoundedRect(right, 10, 10)
        area = right.adjusted(14, 9, -14, -6)
        cue = ('开场', '主曲', '压轴')[show.index] if live else ('谢幕' if show.complete else '等待重试' if show.failed else '即将开场')
        p.setPen(QColor('#a7dfd6'));p.setFont(QFont(self.font().family(), 10, QFont.Bold))
        p.drawText(area, Qt.AlignLeft | Qt.AlignTop, cue)
        p.setFont(font);p.setPen(QColor('#fffaed'))
        p.drawText(QRectF(area.left(),area.top()+21,text_width,title_height), flags, title)
        if live:
            p.setFont(QFont(self.font().family(), 9))
            p.setPen(QColor('#d5e9e4'))
            p.drawText(area, Qt.AlignRight | Qt.AlignTop, f'{_timecode(clip_elapsed)} / {_timecode(round(duration))}')
            bar = QRectF(area.x(), right.bottom()-17, text_width, 3)
            p.fillRect(bar, QColor('#5b747c'))
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width()*min(1.,clip_elapsed/duration), 3), QColor('#a7dfd6'))
        p.end()


class SongLabel(QLabel):
    """Fit local song metadata into the allotted width, keeping the full title available."""
    def __init__(self, lines=1):
        super().__init__()
        self.lines = lines
        self.full_title = ''
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_song(self, title):
        self.full_title = title
        self.setAccessibleName(title)
        self.setToolTip(title)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        text = ' '.join(self.full_title.splitlines())
        width = max(1, self.contentsRect().width())
        metrics = self.fontMetrics()
        if self.lines == 1 or metrics.horizontalAdvance(text) <= width:
            self.setText(metrics.elidedText(text, Qt.ElideRight, width))
            return
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(width)
        layout.endLayout()
        # Qt counts UTF-16 code units. QString slicing in Python counts Unicode code points.
        raw = text.encode('utf-16-le')
        split = line.textLength()*2
        first = raw[:split].decode('utf-16-le').rstrip()
        rest = raw[split:].decode('utf-16-le').lstrip()
        self.setText(first+'\n'+metrics.elidedText(rest, Qt.ElideRight, width))


class AnswerButton(QPushButton):
    def __init__(self, index):
        super().__init__()
        self.letter = 'ABC'[index]
        self.setObjectName('answer')
        self.setMinimumHeight(46)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 12, 5)
        layout.setSpacing(12)
        self.key = QLabel(self.letter)
        self.key.setObjectName('answerKey')
        self.key.setFixedSize(32, 32)
        self.key.setAlignment(Qt.AlignCenter)
        self.caption = SongLabel(lines=2)
        for part in (self.key, self.caption):
            part.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.key)
        layout.addWidget(self.caption, 1)
        self.setShortcut(QKeySequence(self.letter))

    def setText(self, text):
        self.caption.set_song(text)
        self.setToolTip(text)
        self.set_result('')

    def set_result(self, result):
        set_role(self, 'result', result)
        self.key.setText({'correct': '正确', 'picked': '已选'}.get(result, self.letter))
        description = {'correct':'正确答案', 'picked':'你的选择'}.get(result, self.letter)
        self.setAccessibleName(f'{description} · {self.caption.full_title}')


class SetListStrip(QWidget):
    def __init__(self):
        super().__init__()
        self.cells = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for _ in range(3):
            frame = QFrame()
            frame.setObjectName('programSlot')
            column = QVBoxLayout(frame)
            column.setContentsMargins(9, 6, 9, 6)
            column.setSpacing(1)
            cue, title = QLabel(), SongLabel()
            cue.setObjectName('muted');title.setObjectName('entryTitle')
            column.addWidget(cue);column.addWidget(title)
            row.addWidget(frame, 1)
            self.cells.append((frame, cue, title))

    def display(self, tracks, current, current_label='演出中'):
        for index, (frame, cue, title) in enumerate(self.cells):
            state = 'current' if index == current else 'done' if index < current else 'next'
            set_role(frame, 'cue', state)
            part = ('开场', '主曲', '压轴')[index]
            cue.setText(part + ' · ' + {'current':current_label, 'done':'已演', 'next':'待演'}[state])
            title.set_song(tracks[index]['title'])


class GuessGame(LibraryDialog):
    def __init__(self,mod,parent=None):
        super().__init__(mod,'天依 · 猜歌挑战','听八秒旋律，从三首歌里找出答案。','cassette',parent);self.resize(620,228)
        self.start_button=QPushButton('开始三题猜歌');self.start_button.setObjectName('primary');self.start_button.setEnabled(False);self.start_button.clicked.connect(self.start_game);self.box.addWidget(self.start_button,0,Qt.AlignLeft)
        self.question_panel=panel=QFrame();panel.setObjectName('section');panel_box=QVBoxLayout(panel);panel_box.setContentsMargins(16,14,16,14);panel_box.setSpacing(8);panel.hide()
        heading=QHBoxLayout();panel_box.addLayout(heading)
        self.question_title=QLabel();self.question_title.setObjectName('sectionTitle');heading.addWidget(self.question_title,1)
        self.clip_clock=QLabel();self.clip_clock.setObjectName('muted');heading.addWidget(self.clip_clock)
        self.question_progress=QProgressBar();self.question_progress.setRange(0,80);self.question_progress.setTextVisible(False);self.question_progress.setFixedHeight(5);panel_box.addWidget(self.question_progress)
        self.question_progress.setAccessibleName('试听进度');self.player.progress.connect(self.clip_progress)
        self.answers=[]
        for i in range(3):
            button=AnswerButton(i);button.clicked.connect(lambda checked=False,n=i:self.answer(n));panel_box.addWidget(button);self.answers.append(button)
        row=QHBoxLayout();self.relisten=QPushButton('再听一次');self.relisten.setEnabled(False);self.relisten.clicked.connect(self.replay_clip);row.addWidget(self.relisten)
        self.next_button=QPushButton('下一题');self.next_button.clicked.connect(self.next_question);self.next_button.setEnabled(False);row.addWidget(self.next_button)
        self.change_tracks=QPushButton('返回选歌');self.change_tracks.hide();self.change_tracks.clicked.connect(self.select_again);row.addWidget(self.change_tracks)
        row.addStretch();panel_box.addLayout(row);self.box.addWidget(panel);self.box.addStretch()
        self.player.started.connect(self.clip_started);self.player.finished.connect(self.clip_done)
        self.index=0;self.correct=0;self.questions=[];self.current=None
        self.answered=False;self.completed=False;self.clip_ready=False;self.clip_failed=False

    def ready(self,tracks):
        if self.questions:return
        distinct = {}
        for track in tracks:
            title = track['title']
            if track['duration'] >= 15 and len(title) >= 2 and not re.fullmatch(r'[\d\W_]+', title):
                distinct.setdefault(title.casefold(), track)
        tracks = list(distinct.values())
        super().ready(tracks)
        self.start_button.setEnabled(len(tracks)>=3 and not self.questions)
        if len(tracks)<3:self.label.setText('猜歌需要至少三首歌名不同、可读取的歌曲，可以补充本地歌曲。')

    def start_game(self):
        if len(self.tracks)<3 or self.questions:return
        self.questions=random.sample(self.tracks,3);self.session=uuid.uuid4().hex
        self.start_button.hide();self.add.hide();self.library_card.hide();self.question_panel.show();self.next_question()

    def next_question(self):
        if self.closed or self.completed or not self.questions or (self.current and not self.answered):return
        if self.index>=3:self.complete();return
        self.current=self.questions[self.index];self.options=random.sample([x for x in self.tracks if x!=self.current],2)+[self.current]
        random.shuffle(self.options);self.answered=False;self.clip_ready=False;self.next_button.setEnabled(False)
        for button,track in zip(self.answers,self.options):button.setText(track['title']);button.setEnabled(False)
        self.header.stamp.set_name('cassette');self.header.detail.setText('听完片段，点击歌名或按 A、B、C 作答。')
        self.clip_offset=min(self.current['duration']-9,self.current['duration']*random.uniform(.2,.65))
        self.play_clip()

    def replay_clip(self):
        if self.answered or self.completed or not (self.clip_ready or self.clip_failed):return
        self.play_clip()

    def play_clip(self):
        self.clip_failed=self.clip_ready=False
        self.library_card.hide();self.change_tracks.hide()
        self.relisten.setText('再听一次');self.relisten.setEnabled(False);self.clip_progress(0.)
        for button in self.answers:button.setEnabled(False)
        self.question_title.setText(f'第 {self.index+1} / 3 题 · 准备片段')
        self.player.play(self.current['path'],self.clip_offset,8)

    def clip_started(self):
        if not self.closed and self.current and not self.clip_failed and not self.answered:
            self.question_title.setText(f'第 {self.index+1} / 3 题 · 正在试听')

    def error(self,message):
        if self.closed or self.completed or not self.current:return
        self.clip_failed=True;self.clip_ready=False
        self.question_title.setText(f'第 {self.index+1} / 3 题 · 试听失败')
        for button in self.answers:button.setEnabled(False)
        self.relisten.setText('重试试听');self.relisten.setEnabled(True);self.change_tracks.show()
        super().error(message)

    def select_again(self):
        self.player.stop()
        self.questions=[];self.current=None;self.index=self.correct=0
        self.answered=self.clip_ready=self.clip_failed=False
        self.question_panel.hide();self.change_tracks.hide();self.add.show();self.start_button.show()
        self.start_button.setEnabled(False);self.label.setText('重新读取本地歌曲…')
        self.header.detail.setText('听八秒旋律，从三首歌里找出答案。')
        self.rescan()

    def clip_progress(self, seconds):
        if self.closed or self.answered or self.completed or self.clip_failed:
            return
        tenth = max(0, min(80, int(seconds*10)))
        self.question_progress.setValue(tenth)
        stamp = f'0:{tenth//10:02} / 0:08'
        if stamp != self.clip_clock.text():self.clip_clock.setText(stamp)

    def clip_done(self):
        if self.closed or self.answered or self.completed or self.clip_failed or not self.current or self.index>=len(self.questions):return
        self.clip_progress(8.);self.clip_ready=True;self.relisten.setEnabled(True);self.question_title.setText(f'第 {self.index+1} / 3 题 · 选择歌名')
        for button in self.answers:button.setEnabled(True)

    def answer(self,n):
        if self.answered or not self.clip_ready or self.completed:return
        self.answered=True;self.relisten.setEnabled(False);self.question_title.setText(f'第 {self.index+1} / 3 题 · 已作答')
        self.library_card.show()
        for i, button in enumerate(self.answers):
            button.setEnabled(False)
            button.set_result('correct' if self.options[i] == self.current else 'picked' if i == n else '')
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
        self.header.stamp.set_name('happy' if self.options[n]==self.current else 'shy')
        self.index+=1;self.next_button.setText('完成挑战' if self.index==3 else '下一题');self.next_button.setEnabled(True)

    def complete(self):
        if self.completed or self.index != 3 or len(self.questions) != 3:return
        self.player.close()
        self.completed=True;self.next_button.setEnabled(False);self.question_panel.hide();self.library_card.show();self.header.detail.setText(f'挑战完成 · 认出了 {self.correct} / 3 首歌。')
        judge=SimpleNamespace(score=round(self.correct/3*1000000),best=self.correct,perfect=self.correct,good=0,misses=3-self.correct,holds=0)
        before=self.mod.store.stage
        self.mod.store.complete_round(self.session,'quiz:'+self.session,'三首真实歌曲',judge,kind='quiz')
        if self.correct==3:
            with self.mod.store.db:self.mod.store.card('quiz:three','三首都认出来啦','这一轮歌曲：'+'、'.join(t['title'] for t in self.questions))
        self.mod.after_growth(before);self.label.setText('这一轮一起听了《'+'》、《'.join(t['title'] for t in self.questions)+'》。')


class WeeklyShow(LibraryDialog):
    selection_hint = '选三首本地歌曲或片段，从头到尾依次播放。'

    def __init__(self,mod,parent=None):
        super().__init__(mod,'天依 · 三曲小演出',self.selection_hint,'ticket',parent)
        playlist=QFrame();self.playlist_panel=playlist;playlist.setObjectName('section');playlist_box=QVBoxLayout(playlist);playlist_box.setContentsMargins(14,10,14,10)
        title=QLabel('节目单 · 选择三首不同的歌');title.setStyleSheet('font-weight:bold;font-size:12pt;');playlist_box.addWidget(title)
        self.selectors=[]
        self.song_titles=QStringListModel(self)
        for i in range(3):
            row=QHBoxLayout();row.addWidget(QLabel(('开场','主曲','压轴')[i]));combo=QComboBox();combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);combo.setModel(self.song_titles);row.addWidget(combo,1);playlist_box.addLayout(row);self.selectors.append(combo)
        row=QHBoxLayout();row.addWidget(QLabel('谢幕动作'));self.encore=QComboBox()
        for name,key in [('挥手谢幕','wave'),('转身谢幕','turn'),('开心谢幕','happy')]:self.encore.addItem(name,key)
        row.addWidget(self.encore,1);playlist_box.addLayout(row);self.box.addWidget(playlist)
        self.program_line=SetListStrip();self.program_line.hide();self.box.addWidget(self.program_line)
        self.stage=ShowStage(self);self.box.addWidget(self.stage,1)
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setAccessibleName('全场演出进度');self.progress.setTextVisible(False);self.progress.setFixedHeight(6);self.progress.hide();self.box.addWidget(self.progress)
        row=QHBoxLayout();self.start_button=QPushButton('开始三曲演出');self.start_button.setObjectName('primary');self.start_button.setEnabled(False);self.start_button.clicked.connect(self.start_show);row.addWidget(self.start_button)
        self.pause_button=QPushButton('暂停演出');self.pause_button.hide();self.pause_button.clicked.connect(self.pause);row.addWidget(self.pause_button)
        self.edit_button=QPushButton('更换节目单');self.edit_button.hide();self.edit_button.clicked.connect(self.edit_program);row.addWidget(self.edit_button)
        self.open_album=QPushButton('打开纪念册');self.open_album.hide();self.open_album.clicked.connect(lambda:self.mod.open(2));row.addWidget(self.open_album);row.addStretch();self.box.addLayout(row)
        self.player.started.connect(self.act_started);self.player.finished.connect(self.next_song);self.player.progress.connect(self.update_progress)
        self.player.source_duration.connect(self.update_duration)
        self.program=[];self.index=-1;self.last_action=0.;self.failed=False;self.complete=False
        for combo in self.selectors:
            combo.currentIndexChanged.connect(self.selection_changed)

    def ready(self,tracks):
        if self.program:return
        super().ready(tracks)
        self.song_titles.setStringList([f"{track['title']}  ·  {_timecode(round(track['duration']))}" for track in tracks])
        for i,combo in enumerate(self.selectors):
            combo.setCurrentIndex(min(i,len(tracks)-1))
        self.selection_changed()
        self.label.setText(f'本地歌单里有 {len(tracks)} 首可选。' if len(tracks)>=3 else '请补充三个不同的本地音频文件，剪好的短片段也可以。')

    def selected_tracks(self):
        tracks = []
        for combo in self.selectors:
            index = combo.currentIndex()
            if 0 <= index < len(self.tracks):
                tracks.append(self.tracks[index])
        return tracks

    def selection_changed(self):
        if self.program:return
        tracks = self.selected_tracks()
        ready = len({track['path'] for track in tracks}) == 3
        self.start_button.setEnabled(ready)
        if ready:
            total = sum(track['duration'] for track in tracks)
            self.header.detail.setText(f'三首依次完整播放 · 全场 {_timecode(round(total))}')
        else:
            self.header.detail.setText(self.selection_hint)

    def start_show(self):
        if self.failed and self.program:
            self.failed=False
            self.play_act()
            return
        if self.program:return
        program = [track.copy() for track in self.selected_tracks()]
        if len({track['path'] for track in program})!=3:self.label.setText('请选择三首不同的歌曲。');return
        self.stage.theme=self.mod.store.preference('theme','');self.stage.stage_number=self.mod.store.stage
        self.stage.elapsed=0;self.playlist_panel.hide();self.program_line.show();self.library_card.hide();self.progress.show()
        self.program=program;self.session=uuid.uuid4().hex;self.start_button.hide();self.add.setEnabled(False)
        for combo in self.selectors:combo.setEnabled(False)
        self.encore.setEnabled(False)
        self.next_song()

    def edit_program(self):
        self.player.stop()
        self.failed=False;self.index=-1;self.program=[]
        self.stage.elapsed=0.;self.stage.update();self.progress.hide();self.program_line.hide()
        self.edit_button.hide();self.pause_button.hide();self.playlist_panel.show()
        for combo in self.selectors:combo.setEnabled(True)
        self.encore.setEnabled(True);self.add.setEnabled(True)
        self.start_button.setText('开始三曲演出');self.start_button.show()
        self.selection_changed()
        self.label.setText('可以更换歌曲，也可以补充本地歌曲。')

    def pause(self):
        if not self.player.loaded or not self.player.live:return
        self.player.toggle_pause();self.pause_button.setText('继续演出' if self.player.paused else '暂停演出')
        self.program_line.display(self.program,self.index,'已暂停' if self.player.paused else '演出中')
        if self.player.paused:self.stage.timer.stop()
        elif self.isVisible() and not self.isMinimized() and self.player.live and self.player.loaded:self.stage.timer.start()

    def next_song(self):
        if self.closed or self.failed or self.complete or not self.program:return
        self.index+=1
        if self.index>=len(self.program):
            self.complete=True;self.player.close();self.progress.setValue(self.progress.maximum());self.mod.store.record_show(self.session,self.program)
            self.pause_button.hide();self.stage.timer.stop();self.open_album.show();self.stage.update()
            self.program_line.display(self.program, len(self.program));self.header.stamp.set_name('wings')
            total = sum(track['duration'] for track in self.program)
            self.header.detail.setText(f'全场 {_timecode(round(total))} · 三首已唱完，节目单已收进纪念册。')
            self.mod.services.act(self.encore.currentData());self.mod.refresh();self.label.setText('三曲演出完成！节目单已经收进纪念册，可导出纪念卡。');return
        self.play_act()

    def play_act(self):
        self.stage.timer.stop();self.stage.elapsed=0.;self.update_show_clock()
        self.start_button.hide();self.edit_button.hide();self.library_card.hide();self.pause_button.hide()
        self.program_line.display(self.program, self.index,'准备中')
        self.stage.update()
        self.player.play(self.program[self.index]['path'])

    def update_duration(self, seconds):
        if self.closed or self.failed or not 0 <= self.index < len(self.program):return
        if self.program[self.index]['duration'] != seconds:
            self.program[self.index]['duration'] = seconds
            self.update_show_clock()
            self.stage.update()

    def update_show_clock(self):
        total = sum(track['duration'] for track in self.program)
        completed = sum(track['duration'] for track in self.program[:self.index])
        elapsed = completed + min(self.stage.elapsed, self.program[self.index]['duration'])
        self.progress.setValue(round(self.progress.maximum() * elapsed / total))
        text = f'第 {self.index+1} 幕 · 全场 {_timecode(elapsed)} / {_timecode(round(total))}'
        if self.header.detail.text() != text:
            self.header.detail.setText(text)

    def act_started(self):
        if self.closed or self.failed or self.complete or not self.program:return
        import time
        self.last_action=time.monotonic()
        self.pause_button.setText('暂停演出');self.pause_button.show()
        self.program_line.display(self.program,self.index)
        self.mod.services.act('sing')

    def update_progress(self,elapsed):
        if self.closed or self.failed or self.complete or not 0<=self.index<len(self.program):return
        self.stage.elapsed=elapsed
        if self.isVisible() and not self.isMinimized() and self.player.live and self.player.loaded and not self.player.paused and not self.stage.timer.isActive():self.stage.timer.start()
        self.stage.update()
        self.update_show_clock()
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
        if self.closed or self.complete or not self.program:return
        self.failed=True;self.stage.timer.stop();self.player.stop();self.stage.update()
        self.program_line.display(self.program,self.index,'播放失败')
        self.pause_button.hide();self.edit_button.show()
        self.start_button.setText('重试本幕');self.start_button.setEnabled(True);self.start_button.show()
        super().error(message)
