"""Preserve media and playback intent while Windows rebuilds an audio endpoint."""
from dataclasses import dataclass
from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer


@dataclass
class ResumePoint:
    source: QUrl
    position: int
    state: object
    seekable: bool


class OutputSwitch(QObject):
    def __init__(self, player, audio, parent=None):
        super().__init__(parent)
        self.player, self.audio = player, audio
        self.pending = None
        self.routing = False
        self.reloaded = False
        self.verify_point = None
        self.settle = QTimer(self)
        self.settle.setSingleShot(True)
        self.settle.timeout.connect(self.settled)
        self.fallback = QTimer(self)
        self.fallback.setSingleShot(True)
        self.fallback.timeout.connect(self.reload_once)
        self.verify = QTimer(self)
        self.verify.setSingleShot(True)
        self.verify.timeout.connect(self.verify_progress)
        for signal in (player.durationChanged, player.seekableChanged, player.mediaStatusChanged):
            signal.connect(self.restore)

    def before_change(self):
        self.settle.stop()
        self.fallback.stop()
        self.verify.stop()
        self.verify_point = None
        self.reloaded = False
        if self.player.source().isEmpty():
            return
        if self.pending is None:
            self.pending = ResumePoint(self.player.source(), self.player.position(),
                                       self.player.playbackState(), self.player.isSeekable())
        self.routing = True
        # Do not discard the decoder/network buffer just to switch speakers.
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()

    def after_change(self):
        if self.pending is None:
            self.routing = False
            return
        self.settle.start(40)
        if not self.audio.device().isNull():
            self.fallback.start(1500)

    def settled(self):
        self.routing = False
        self.restore()

    def restore(self, *_):
        point = self.pending
        if point is None or self.routing or self.audio.device().isNull():
            return
        if point.source != self.player.source():
            self.cancel()
            return
        ready = self.player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.BufferedMedia)
        if not ready or (point.seekable and not self.player.isSeekable()):
            return
        self.pending = None  # Seek/play can synchronously emit media signals.
        self.fallback.stop()
        if self.player.isSeekable():
            self.player.setPosition(point.position)
        if point.state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()
            if not self.reloaded:
                self.verify_point = point
                self.verify.start(650)
        elif point.state == QMediaPlayer.PlaybackState.PausedState:
            self.player.pause()

    def reload_once(self):
        if self.pending is None or self.audio.device().isNull() or self.reloaded:
            return
        self.reloaded = True
        self.routing = True
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setSource(self.pending.source)
        self.settle.start(40)

    def verify_progress(self):
        point, self.verify_point = self.verify_point, None
        if (point is None or point.source != self.player.source() or self.pending is not None
                or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                or self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia):
            return
        # WMF can report Buffered/Playing before the new endpoint actually runs.
        if self.player.position() <= point.position + 20:
            self.pending = point
            self.reload_once()

    def cancel(self):
        self.pending = None
        self.routing = False
        self.settle.stop()
        self.fallback.stop()
        self.verify.stop()
        self.verify_point = None

    def play(self):
        if self.pending:
            self.pending.state = QMediaPlayer.PlaybackState.PlayingState
        else:
            self.player.play()

    def pause(self):
        self.verify.stop()
        self.verify_point = None
        if self.pending:
            self.pending.state = QMediaPlayer.PlaybackState.PausedState
        self.player.pause()

    def seek(self, position):
        self.verify.stop()
        self.verify_point = None
        if self.pending:
            self.pending.position = position
        else:
            self.player.setPosition(position)
