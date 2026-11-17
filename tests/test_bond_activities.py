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
from PySide6.QtCore import Qt,QEvent,QThread,Signal
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

    def test_player_pause_keeps_clock_and_manual_music_wins(self):
        p=ClipPlayer(self.mod,None);self.addCleanup(p.stop)
        p.live=True;p.loaded=True;p.token='token';p.offset=0;p.duration=30;p.last_position=-1;p.last_advance=0
        with patch.object(p.player,'pause'),patch.object(p.player,'play'):
            p.toggle_pause();self.assertTrue(p.paused);p.tick();self.assertTrue(p.live)
            self.mod.services.snapshot.return_value['playing']=True;p.tick();self.assertFalse(p.live)
        self.mod.services.audio_release.assert_called_once_with('token')

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
