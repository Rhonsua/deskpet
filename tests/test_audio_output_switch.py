import unittest
from PySide6.QtCore import QCoreApplication, QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer as MP
from audio.output_switch import OutputSwitch


class Player(QObject):
    durationChanged = Signal(int)
    seekableChanged = Signal(bool)
    mediaStatusChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.url = QUrl('https://example.invalid/song.mp3')
        self.pos, self.state, self.seekable = 12500, MP.PlaybackState.PlayingState, True
        self.status = MP.MediaStatus.BufferedMedia
        self.loads = []

    def source(self): return self.url
    def position(self): return self.pos
    def playbackState(self): return self.state
    def isSeekable(self): return self.seekable
    def mediaStatus(self): return self.status
    def pause(self): self.state = MP.PlaybackState.PausedState
    def play(self): self.state = MP.PlaybackState.PlayingState
    def stop(self): self.state, self.pos = MP.PlaybackState.StoppedState, 0
    def setPosition(self, value): self.pos = value
    def setSource(self, value): self.url = value; self.loads.append(value)


class Audio:
    absent = False
    def device(self): return self
    def isNull(self): return self.absent


class OutputSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.player, self.audio = Player(), Audio()
        self.switch = OutputSwitch(self.player, self.audio)
        self.addCleanup(self.switch.cancel)

    def route(self):
        self.switch.before_change()
        self.player.pos = 0  # Windows can reset position when rebuilding the graph.
        self.switch.after_change()
        self.switch.settled()

    def test_playing_and_paused_switch_without_reloading_source(self):
        for state in (MP.PlaybackState.PlayingState, MP.PlaybackState.PausedState):
            self.player.state = state
            self.route()
            self.assertEqual(self.player.pos, 12500)
            self.assertEqual(self.player.state, state)
            self.assertEqual(self.player.loads, [])

    def test_rapid_switch_keeps_original_progress_and_latest_pause_seek(self):
        self.switch.before_change()
        self.player.pos = 0
        self.switch.after_change()
        self.switch.before_change()
        self.switch.seek(7000)
        self.switch.pause()
        self.switch.after_change()
        self.switch.settled()
        self.assertEqual(self.player.pos, 7000)
        self.assertEqual(self.player.state, MP.PlaybackState.PausedState)

    def test_stop_or_new_song_cancels_pending_resume(self):
        self.switch.before_change()
        self.switch.after_change()
        self.switch.cancel()
        self.player.stop()
        self.player.setSource(QUrl('file:///new.wav'))
        self.switch.settled()
        self.switch.reload_once()
        self.assertEqual(self.player.state, MP.PlaybackState.StoppedState)
        self.assertEqual(len(self.player.loads), 1)

    def test_non_seekable_stream_does_not_wait_forever(self):
        self.player.seekable = False
        self.route()
        self.assertEqual(self.player.state, MP.PlaybackState.PlayingState)
        self.assertIsNone(self.switch.pending)

    def test_unready_backend_uses_reload_only_as_fallback(self):
        self.switch.before_change()
        self.player.status = MP.MediaStatus.LoadingMedia
        self.switch.after_change()
        self.switch.settled()
        self.assertEqual(self.player.loads, [])
        self.switch.reload_once()
        self.assertEqual(self.player.loads, [QUrl(), QUrl('https://example.invalid/song.mp3')])
        self.player.status = MP.MediaStatus.LoadedMedia
        self.switch.settled()
        self.assertEqual(self.player.pos, 12500)
        self.assertEqual(self.player.state, MP.PlaybackState.PlayingState)

    def test_disconnected_outputs_keep_resume_until_reconnected(self):
        self.audio.absent = True
        self.route()
        self.switch.reload_once()
        self.assertIsNotNone(self.switch.pending)
        self.assertEqual(self.player.loads, [])
        self.audio.absent = False
        self.route()
        self.assertEqual(self.player.pos, 12500)
        self.assertEqual(self.player.state, MP.PlaybackState.PlayingState)

    def test_buffered_but_stalled_backend_reloads_once(self):
        self.route()
        self.switch.verify_progress()
        self.assertEqual(len(self.player.loads), 2)
        self.switch.settled()
        self.switch.verify_progress()
        self.switch.reload_once()
        self.assertEqual(len(self.player.loads), 2)

    def test_progressing_backend_keeps_buffer_and_pause_cancels_watchdog(self):
        self.route()
        self.player.pos += 300
        self.switch.verify_progress()
        self.assertEqual(self.player.loads, [])
        self.route()
        self.switch.pause()
        self.switch.verify_progress()
        self.assertEqual(self.player.loads, [])


if __name__ == '__main__': unittest.main()
