import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.activities import GuessGame,WeeklyShow,LibraryDialog

class ActivityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.store=BondStore(':memory:');self.mod=SimpleNamespace(active=True,store=self.store,after_growth=Mock(),refresh=Mock(),open=Mock(),services=SimpleNamespace(library=lambda:[],act=Mock(),audio_claim=Mock(return_value='token'),audio_release=Mock(),audio_valid=lambda _:True,snapshot=lambda:dict(playing=False,volume=.5)))
        self.tracks=[dict(path=str(i)+'.mp3',title='歌曲 '+str(i),duration=60) for i in range(3)]
    def test_relisten_same_clip_and_answer_once(self):
        with patch.object(LibraryDialog,'scan'):
            d=GuessGame(self.mod);d.setAttribute(__import__('PySide6').QtCore.Qt.WA_DeleteOnClose,False);d.ready(self.tracks);d.player.play=Mock(return_value=True);d.start_game()
            original=d.player.play.call_args;d.clip_done();d.replay_clip();self.assertEqual(d.player.play.call_args,original)
            d.answer(0);self.assertEqual(d.index,0);d.clip_done();d.answer(d.options.index(d.current));self.assertEqual(d.index,1)
            d.clip_done();d.answer(0);self.assertEqual(d.index,1);d.close()
    def test_show_failure_and_frozen_animation(self):
        with patch.object(LibraryDialog,'scan'):
            d=WeeklyShow(self.mod);d.setAttribute(__import__('PySide6').QtCore.Qt.WA_DeleteOnClose,False);d.ready(self.tracks);d.player.play=Mock(return_value=True);d.show();d.start_show()
            self.assertFalse(d.stage.timer.isActive());d.player.live=True;d.player.loaded=True;d.update_progress(5);self.assertTrue(d.stage.timer.isActive())
            d.hide();self.assertFalse(d.stage.timer.isActive());d.error('播放失败');d.player.finished.emit()
            self.assertFalse(d.complete);self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0],0)
            d.mod.services.act.reset_mock();d.update_progress(25);d.mod.services.act.assert_not_called();self.assertFalse(d.stage.timer.isActive());d.close()
    def tearDown(self):self.store.close()

if __name__=='__main__':unittest.main()
