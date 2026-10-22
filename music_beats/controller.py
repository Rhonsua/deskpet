"""Small UI controller. Analysis is opt-in and isolated in a cancellable process."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
from PySide6.QtCore import QObject,Signal,QProcess
from .core import clock, netease_source_id

@dataclass(frozen=True)
class BeatSample:
    beat_index:int=-1
    phase:float=0.0
    available:bool=False
    bpm:float=0.0

class BeatController(QObject):
    changed=Signal()
    analysisFinished=Signal(bool)
    def __init__(self,data_dir,parent=None):
        super().__init__(parent)
        self.directory=Path(data_dir)/'beats';self.source='';self.path=None;self.analysis={};self.manual={};self.tag_bpm=0
        self.status='未选择音源';self.progress=0;self.process=None;self.buffer=b'';self.fingerprint='';self._result=False
        self.enabled=self._read(self.directory/'settings.json').get('enabled') is True
        self._cache_path=None;self._pending=False;self._online_identity=''
    def _read(self,path):
        try:
            if path.stat().st_size>4*1024*1024:return {}
            value=json.loads(path.read_text(encoding='utf-8'))
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}
    def _write(self,path,value):
        self.directory.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)
    @property
    def analyzing(self):return self.process is not None
    def set_enabled(self,value):
        if type(value) is not bool:raise ValueError('节拍开关须为布尔值')
        self.enabled=value
        if not value:self.cancel()
        try:self._write(self.directory/'settings.json',{'version':1,'enabled':value})
        except OSError:self.status='开关已应用，但设置保存失败'
        self.changed.emit()
    def has_timing(self):
        try:
            bpm=float(self.manual.get('bpm',0)) or float(self.analysis.get('bpm',0)) or self.tag_bpm
            return math.isfinite(bpm) and 20<=bpm<=400
        except (TypeError,ValueError):return False
    def _finish_signal(self,success):
        if self._pending:
            self._pending=False
            self.analysisFinished.emit(bool(success))
    def restore_online(self,source_key,identity):
        if netease_source_id(source_key) is None:raise ValueError('在线节拍需要有效网易云音源')
        if not isinstance(identity,str) or not identity or len(identity)>4096:raise ValueError('在线音频版本标识无效')
        self.set_source(source_key)
        if self._online_identity!=identity:
            self.cancel();self.analysis={};self._online_identity=identity
        self.fingerprint=hashlib.sha256((source_key+'|'+identity+'|beats-v1').encode()).hexdigest()
        self._cache_path=self.directory/('online-'+self.fingerprint+'.json')
        candidate=self._read(self._cache_path)
        if self._valid(candidate):
            self.analysis=candidate;self.status='已有歌曲节拍缓存，下次播放直接复用';self.changed.emit();return True
        self.changed.emit();return False
    def analyze_online(self,path,identity):
        if netease_source_id(self.source) is None:raise ValueError('请先选择网易云歌曲')
        self.restore_online(self.source,identity)
        self._start_analysis(Path(path))
    def _manual_path(self):return self.directory/('manual-'+hashlib.sha256(self.source.encode()).hexdigest()+'.json')
    def set_source(self,source_key):
        if source_key.startswith('netease:') and netease_source_id(source_key) is None:
            raise ValueError('网易云音源需要有效歌曲ID')
        if source_key==self.source:return
        self.cancel();self.source=source_key;self.path=None;self.analysis={};self.tag_bpm=0;self.fingerprint='';self.progress=0
        self._cache_path=None;self._online_identity=''
        self.manual=self._read(self._manual_path()) if source_key else {}
        try:
            b=float(self.manual.get('bpm',0));o=float(self.manual.get('offset_ms',0));v=float(self.manual.get('speed',1))
            if not math.isfinite(b) or (b!=0 and not 20<=b<=400) or not math.isfinite(o) or abs(o)>3600000 or v not in (.5,1,2):self.manual={}
        except (TypeError,ValueError):self.manual={}
        self.status='仅支持手动BPM'
        if netease_source_id(source_key):
            self.status='开启后首次播放自动分析，之后复用歌曲节拍缓存'
        if source_key.startswith('local:'):
            self.path=Path(source_key[6:])
            try:
                stat=self.path.stat()
                identity=f'{self.path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|v1'
                self.fingerprint=hashlib.sha256(identity.encode()).hexdigest()
                self._cache_path=self.directory/('analysis-'+self.fingerprint+'.json')
                candidate=self._read(self._cache_path)
                if self._valid(candidate):self.analysis=candidate
                self.tag_bpm=self._tag(self.path)
                self.status='已有节拍缓存' if self.analysis else ('已读取BPM标签；可分析起拍' if self.tag_bpm else '可分析本地音频或手动输入BPM')
            except OSError:self.status='本地文件无法读取；仍可手动BPM'
        self.changed.emit()
    @staticmethod
    def _valid(data):
        try:
            bpm=float(data['bpm']);beats=data['beats_ms']
            return 20<=bpm<=400 and isinstance(beats,list) and 2<=len(beats)<=1000000 and all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in beats) and all(a<b for a,b in zip(beats,beats[1:]))
        except (KeyError,TypeError,ValueError):return False
    @staticmethod
    def _tag(path):
        try:
            from mutagen import File
            song=File(str(path),easy=True)
            values=song.get('bpm',[]) if song is not None else []
            if not values:
                song=File(str(path));values=song.get('TBPM',[]) if song is not None else []
            value=float(str(values[0] if isinstance(values,(list,tuple)) else values))
            return value if math.isfinite(value) and 20<=value<=400 else 0
        except Exception:return 0
    def set_manual(self,bpm=0,offset_ms=0,speed=1):
        if not self.source:raise ValueError("请先选择播放音源")
        bpm=float(bpm);offset_ms=float(offset_ms);speed=float(speed)
        if not math.isfinite(bpm) or (bpm!=0 and not 20<=bpm<=400) or not math.isfinite(offset_ms) or abs(offset_ms)>3600000 or speed not in (.5,1,2):raise ValueError('无效BPM、偏移或倍率')
        self.manual={'bpm':bpm,'offset_ms':offset_ms,'speed':speed}
        try:self._write(self._manual_path(),self.manual)
        except OSError:self.status='校正已应用，本地保存失败'
        self.changed.emit()
    def sample(self,position_ms,playing):
        if not self.enabled:return BeatSample()
        try:
            manual=float(self.manual.get('bpm',0));bpm=manual or float(self.analysis.get('bpm',0)) or self.tag_bpm
            beats=() if manual else self.analysis.get('beats_ms',())
            return BeatSample(*clock(position_ms,bpm,beats,float(self.manual.get('offset_ms',0)),float(self.manual.get('speed',1))))
        except (ValueError,TypeError,OverflowError):return BeatSample()
    def analyze(self):
        if self.path is None or not self.fingerprint:
            self.status='当前音源没有可分析的本地音频';self.changed.emit();self.analysisFinished.emit(False);return
        self._start_analysis(self.path)
    def _start_analysis(self,path):
        self.cancel();self._pending=True;self.progress=0;self._result=False;self.buffer=b'';self.status='正在分析本地节拍'
        process=QProcess(self);self.process=process
        process.readyReadStandardOutput.connect(self._output)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(lambda error,p=process:self._process_error(p,error))
        if getattr(sys,'frozen',False):program=str(Path(sys.executable).with_name('TianyiWorker.exe'));args=['--beat-worker',str(path)]
        else:
            executable=Path(sys.executable)
            if executable.name.lower()=='pythonw.exe':executable=executable.with_name('python.exe')
            program=str(executable);args=['-m','music_beats.worker',str(path)];process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        process.start(program,args);self.changed.emit()
    def _output(self):
        if not self.process:return
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try:
                data=json.loads(line)
                if not isinstance(data,dict):continue
                if data.get('type')=='progress':
                    progress=data.get('progress')
                    if type(progress) is not int or not 0<=progress<=100:continue
                    self.progress=progress
                elif data.get('type')=='result' and self._valid(data.get('data',{})):
                    self.analysis=data['data'];self._result=True;self.progress=100;self.status='分析完成（估计结果，可手动校正）'
                    try:self._write(self._cache_path,self.analysis)
                    except OSError:self.status='分析完成，但缓存保存失败'
                elif data.get('type')=='error':self._failed(str(data.get('message','分析失败')))
            except (ValueError,KeyError,TypeError):continue
            self.changed.emit()
    def _dispose_process(self,process):
        # Drop Python closures before deferred QObject deletion; the error slot
        # otherwise owns both controller and its child process during destruction.
        process.blockSignals(True)
        for signal in (process.readyReadStandardOutput,process.finished,process.errorOccurred):
            signal.disconnect()
        process.deleteLater()
    def _process_error(self,process,error):
        if process is not self.process:return
        if error==QProcess.ProcessError.FailedToStart:
            self.process=None;self._dispose_process(process)
        self._failed('节拍分析进程无法启动或意外退出')
        if error==QProcess.ProcessError.FailedToStart:self._finish_signal(False)
    def _failed(self,message):self.status=message+'；可用手动BPM或原有固定节奏';self.changed.emit()
    def _finished(self,*_):
        self._output()
        if not self._result and self.status=='正在分析本地节拍':self._failed('未取得可靠节拍')
        if self.process:
            process,self.process=self.process,None;self._dispose_process(process)
        self.changed.emit()
        self._finish_signal(self._result)
    def cancel(self):
        if self.process:
            process=self.process;self.process=None;process.blockSignals(True);process.kill();process.waitForFinished(1000);self._dispose_process(process);self.status='分析已取消';self.changed.emit();self._finish_signal(False)
    def shutdown(self):self.cancel()
    def create_widget(self,parent=None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QDoubleSpinBox,QComboBox,QPushButton,QProgressBar,QCheckBox,QToolButton
        widget=QWidget(parent);widget.setStyleSheet('QWidget{background:white;color:black;}')
        layout=QVBoxLayout(widget);layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        enabled=QCheckBox('跟随歌曲节拍（首次播放自动分析，之后复用）');layout.addWidget(enabled)
        description=QLabel('节拍按实际播放位置同步。开启后首次播放会先解析，缓存后无需重复；自动分析为估计结果。')
        description.setTextFormat(Qt.TextFormat.PlainText);description.setWordWrap(True);layout.addWidget(description)
        label=QLabel();label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);layout.addWidget(label)
        progress=QProgressBar();layout.addWidget(progress)
        toggle=QToolButton();toggle.setText('高级校正');toggle.setCheckable(True);toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon);toggle.setArrowType(Qt.ArrowType.RightArrow);layout.addWidget(toggle)
        advanced=QWidget();advanced.setVisible(False);advanced_layout=QVBoxLayout(advanced)
        form=QFormLayout();bpm=QDoubleSpinBox();bpm.setRange(0,400);bpm.setSpecialValueText('自动');bpm.setSuffix(' BPM');form.addRow('手动速度（0为自动）',bpm)
        offset=QDoubleSpinBox();offset.setRange(-3600000,3600000);offset.setSuffix(' ms');form.addRow('起拍偏移（正值延后）',offset)
        speed=QComboBox();speed.addItems(['半速','正常','倍速']);speed.setCurrentIndex(1);form.addRow('拍点倍率',speed);advanced_layout.addLayout(form)
        buttons=QHBoxLayout();apply=QPushButton('保存校正');analyze=QPushButton('重新分析本地音频');cancel=QPushButton('取消分析')
        for button in (apply,analyze,cancel):buttons.addWidget(button)
        advanced_layout.addLayout(buttons);layout.addWidget(advanced);layout.addStretch(1)
        def expand(checked):advanced.setVisible(checked);toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        toggle.toggled.connect(expand)
        def refresh():
            enabled.blockSignals(True);enabled.setChecked(self.enabled);enabled.blockSignals(False)
            label.setText(self.status if self.enabled else '节拍跟随已关闭。');progress.setValue(self.progress);progress.setVisible(self.analyzing)
            if not bpm.hasFocus():bpm.setValue(float(self.manual.get('bpm',0)))
            if not offset.hasFocus():offset.setValue(float(self.manual.get('offset_ms',0)))
            if not speed.hasFocus():speed.setCurrentIndex((.5,1,2).index(float(self.manual.get('speed',1))))
            apply.setEnabled(bool(self.source));analyze.setEnabled(self.path is not None and not self.analyzing);cancel.setEnabled(self.analyzing)
        def save():
            try:self.set_manual(bpm.value(),offset.value(),(.5,1,2)[speed.currentIndex()])
            except ValueError:label.setText('BPM请输入20～400，或用0选择自动')
        enabled.toggled.connect(self.set_enabled);apply.clicked.connect(save);analyze.clicked.connect(self.analyze);cancel.clicked.connect(self.cancel)
        self.changed.connect(refresh);refresh();return widget
