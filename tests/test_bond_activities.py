"""Activity state transitions with fake media; no music or user data used."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtCore import Qt,QEvent,QThread,Signal,QUrl,QSettings
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.activities import GuessGame,WeeklyShow
from deskpet.mods.bond.playback import ClipPlayer


class ActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=BondStore(Path(self.temp.name)/'bond.db');self.addCleanup(self.store.close)
        self.mod=SimpleNamespace(active=True,store=self.store,after_growth=Mock(),refresh=Mock(),services=SimpleNamespace(
            library=lambda:[],act=Mock(),audio_claim=Mock(return_value='token'),audio_release=Mock(),audio_valid=lambda _:True,
            snapshot=Mock(return_value=dict(playing=False,volume=0))))
        self.tracks=[dict(path=str(i)+'.mp3',title='测试歌曲'+str(i),duration=60) for i in range(3)]
    def dialog(self,cls):
        d=cls(self.mod);d.setAttribute(Qt.WA_DeleteOnClose,False)
        d.scanner=Mock();d.scanner.isRunning.return_value=False
        d.ready(self.tracks);self.addCleanup(d.close)
        return d

    def test_quiz_needs_successful_clip_and_one_answer_each(self):
        d=self.dialog(GuessGame)
        with patch.object(d.player,'play',return_value=True):
            d.start_game();d.answer(0);self.assertEqual(d.index,0)
            for i in range(3):
                d.clip_done();answer=d.options.index(d.current)
                d.answer(answer);d.answer(answer);self.assertEqual(d.index,i+1)
                d.next_question()
        self.assertTrue(d.completed);self.assertEqual(self.store.value['affinity'],10)
        d.complete();self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM results').fetchone()[0],1)

    def test_show_only_three_finished_clips_creates_card_once(self):
        d=self.dialog(WeeklyShow)
        with patch.object(d.player,'play',return_value=True):
            d.start_show();self.assertFalse(d.complete)
            d.player.finished.emit();d.player.finished.emit();self.assertFalse(d.complete)
            d.player.finished.emit();d.player.finished.emit()
        self.assertTrue(d.complete);self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0],1)
        self.assertEqual(self.store.value['affinity'],0)

    def test_failed_show_never_completed(self):
        d=self.dialog(WeeklyShow)
        with patch.object(d.player,'play',return_value=True):d.start_show()
        d.error('测试中断');d.player.finished.emit()
        self.assertFalse(d.complete);self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0],0)

    def test_music_switch_and_pause_do_not_revoke_an_activity(self):
        player=ClipPlayer(self.mod,None);self.addCleanup(player.stop)
        native=Mock()
        native.position.return_value=3500
        native.playbackState.return_value=QMediaPlayer.PlayingState
        native.source.return_value=QUrl()
        player.engine=Mock(player=native)
        self.assertTrue(player.claim())
        player.live=player.loaded=player.seek_sent=True
        player.offset=0;player.duration=8;player.last_position=-1
        player.next_preferences=player.last_advance=time.monotonic()+1
        self.mod.services.snapshot.return_value['playing']=True
        player.toggle_pause();player.tick()
        self.assertTrue(player.paused);self.assertTrue(player.live)
        player.toggle_pause();player.tick()
        self.assertEqual(player.elapsed,3.5)
        player.stop()
        self.mod.services.audio_release.assert_called_once_with('token')

    def test_released_host_can_mix_but_another_game_must_wait(self):
        self.mod.services.audio_claim.return_value=None
        self.mod.services.snapshot.return_value['playing']=True
        quiz,show=ClipPlayer(self.mod,None),ClipPlayer(self.mod,None)
        self.assertTrue(quiz.claim());self.assertFalse(show.claim())
        self.mod.services.snapshot.return_value['playing']=False
        self.assertTrue(quiz.valid())
        quiz.stop()
        self.assertFalse(show.claim())  # An exclusive lease is held by another Mod.
        self.mod.services.audio_claim.return_value='new lease'
        self.assertTrue(show.claim());show.stop()

    def test_window_open_and_close_without_playing_never_open_an_audio_device(self):
        for kind in (GuessGame,WeeklyShow):
            window=self.dialog(kind)
            window.show();self.app.processEvents()
            self.assertIsNone(window.player.engine)
            window.reject()
            self.assertTrue(window.closed);self.assertIsNone(window.player.engine)

    def test_first_clip_sets_real_output_volume_even_at_proxy_default(self):
        self.mod.context=SimpleNamespace(data_dir=Path(self.temp.name))
        self.mod.services.snapshot.return_value['volume']=.6
        clip=ClipPlayer(self.mod,None);self.addCleanup(clip.close)
        clip.legacy_settings=QSettings(str(Path(self.temp.name)/'test.ini'),QSettings.IniFormat)
        with patch('deskpet.music.audio.remote.AudioEngine.start'):
            clip.play('demo.mp3',2,8)
            self.assertIn({'cmd':'volume','value':.6},clip.engine.pending)

    def test_complete_file_waits_for_decoder_end_after_its_reported_length(self):
        self.mod.context = SimpleNamespace(data_dir=Path(self.temp.name))
        clip = ClipPlayer(self.mod, None)
        self.addCleanup(clip.close)
        clip.legacy_settings = QSettings(str(Path(self.temp.name)/'test.ini'), QSettings.IniFormat)
        finished, progress, failed, length = Mock(), Mock(), Mock(), Mock()
        clip.finished.connect(finished)
        clip.progress.connect(progress)
        clip.failed.connect(failed)
        clip.source_duration.connect(length)
        with patch('deskpet.music.audio.remote.AudioEngine.start'):
            clip.play('show.mp3')
            native = clip.engine.player
            native.values.update(status=QMediaPlayer.LoadedMedia.value, duration=4000)
            clip.tick()
            self.assertFalse(any(cmd['cmd']=='seek' for cmd in clip.engine.pending))
            native.values.update(state=QMediaPlayer.PlayingState.value, position=41000)
            clip.tick()
            progress.assert_called_once_with(41.)
            self.assertTrue(clip.live)
            finished.assert_not_called()
            # The Windows player sometimes snaps forward to its MP3 length estimate on EOF.
            native.values.update(position=49000, duration=49000)
            native.mediaStatusChanged.emit(QMediaPlayer.EndOfMedia)
            finished.assert_called_once()
            failed.assert_not_called()
            self.assertAlmostEqual(length.call_args.args[0], 41., delta=.25)

            # A decoder error carried by the same final report is a failure.
            clip.play('broken.mp3')
            native.values.update(status=QMediaPlayer.LoadedMedia.value, duration=9000)
            clip.tick()
            native.values.update(error=QMediaPlayer.FormatError.value, error_text='损坏的文件')
            native.mediaStatusChanged.emit(QMediaPlayer.EndOfMedia)
            failed.assert_called_once()
            finished.assert_called_once()

    def test_closed_dialog_cannot_start_deferred_scan(self):
        d=self.dialog(GuessGame);d.close()
        with patch('deskpet.mods.bond.activities.Scanner') as scanner:d.scan();scanner.assert_not_called()

    def test_close_does_not_wait_for_blocked_scanner(self):
        from deskpet.mods.bond.activities import _scanners
        entered,release=threading.Event(),threading.Event()
        class BlockedScanner(QThread):
            scanned=Signal(list)
            def __init__(self,paths,parent):super().__init__(parent)
            def run(self):
                entered.set();release.wait(5)
                self.scanned.emit([{'title':'late'}])
        d=GuessGame(self.mod);d.setAttribute(Qt.WA_DeleteOnClose,False)
        d.ready=Mock()
        with patch('deskpet.mods.bond.activities.Scanner',BlockedScanner):
            d.scan();scanner=d.scanner
            self.assertTrue(entered.wait(2))
            try:
                d.close()
                self.assertTrue(d.closed)
                self.assertTrue(scanner.isRunning())
                self.assertIn(scanner,_scanners)
            finally:
                release.set()
            deadline=time.monotonic()+3
            while scanner in _scanners and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.005)
            self.app.processEvents()
            self.assertNotIn(scanner,_scanners)
            d.ready.assert_not_called()

    def test_completed_scan_can_restart_and_close(self):
        class QuickScanner(QThread):
            scanned=Signal(list)
            def __init__(self,paths,parent):super().__init__(parent)
            def run(self):self.scanned.emit([])
        d=GuessGame(self.mod);d.setAttribute(Qt.WA_DeleteOnClose,False)
        with patch('deskpet.mods.bond.activities.Scanner',QuickScanner):
            for _ in range(2):
                d.scan()
                self.assertIsNotNone(d.scanner)
                deadline=time.monotonic()+3
                while d.scanner is not None and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.005)
                self.assertIsNone(d.scanner)
            d.close()
            self.assertTrue(d.closed)


if __name__=='__main__':unittest.main()
