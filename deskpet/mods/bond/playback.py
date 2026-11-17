"""Exclusive local clip transport shared by quiz and weekly performances."""
import time
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput


class ClipPlayer(QObject):
    finished=Signal()
    failed=Signal(str)
    progress=Signal(float)

    def __init__(self,mod,parent):
        super().__init__(parent);self.mod=mod;self.token=None;self.live=False;self.loaded=False;self.paused=False
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.player.setAudioOutput(self.audio)
        self.router=mod.services.audio_route(self.audio,self) if hasattr(mod.services,'audio_route') else None
        if self.router:self.router.poll.stop()
        self.player.mediaStatusChanged.connect(self.status);self.player.errorOccurred.connect(lambda *_:self.error('音频无法播放'))
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.tick)

    def play(self,path,offset,duration):
        self.stop()
        self.player.setSource(QUrl())
        self.token=self.mod.services.audio_claim()
        if not self.token:self.failed.emit('请先暂停普通播放或结束另一项互动。');return False
        self.live=True;self.loaded=False;self.paused=False;self.offset=offset;self.duration=duration;self.last_position=-1;self.last_advance=time.monotonic()
        if self.router:self.router.refresh();self.router.poll.start()
        self.audio.setVolume(self.mod.services.snapshot().get('volume',.5))
        self.player.setSource(QUrl.fromLocalFile(path));self.timer.start();return True

    def status(self,status):
        if not self.live:return
        if status==QMediaPlayer.LoadedMedia and not self.loaded:
            self.loaded=True;self.player.setPosition(round(self.offset*1000));self.player.play()
        elif status==QMediaPlayer.EndOfMedia:
            elapsed=self.player.position()/1000-self.offset
            if elapsed>=self.duration-.2:self.done()
            else:self.error('音频提前结束，未完成本次片段。')

    def tick(self):
        if not self.live:return
        if not self.mod.active or not self.mod.services.audio_valid(self.token) or self.mod.services.snapshot()['playing']:
            self.error('已让位给其他播放。');return
        if self.paused:return
        position=self.player.position()
        if position!=self.last_position:self.last_position=position;self.last_advance=time.monotonic()
        if time.monotonic()-self.last_advance>20:self.error('音频加载或播放超时。');return
        if not self.loaded:return
        elapsed=position/1000-self.offset;self.progress.emit(max(0.,elapsed))
        if elapsed>=self.duration:self.done()

    def done(self):self.stop();self.finished.emit()
    def toggle_pause(self):
        if not self.live or not self.loaded:return
        self.paused=not self.paused;self.last_advance=time.monotonic()
        if self.paused:self.player.pause()
        else:self.player.play()
    def error(self,message):
        if not self.live:return
        self.stop();self.failed.emit(message)
    def stop(self):
        self.live=False;self.paused=False;self.timer.stop();self.player.stop()
        self.player.setSource(QUrl())
        if self.router:self.router.poll.stop()
        if self.token:self.mod.services.audio_release(self.token);self.token=None
