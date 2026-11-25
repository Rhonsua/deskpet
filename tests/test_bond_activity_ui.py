import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import time
from unittest.mock import Mock,patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.activities import GuessGame,WeeklyShow,LibraryDialog
from deskpet.mods.bond.stage_art import stage_image

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
    def test_quiz_credits_only_after_three_answered_clips(self):
        self.store.game_completed = Mock()
        with patch.object(LibraryDialog, 'scan'):
            d = GuessGame(self.mod)
            d.ready(self.tracks)
            d.player.play = Mock(return_value=True)
            d.start_game()
            for _ in range(3):
                d.complete()
                self.store.game_completed.assert_not_called()
                d.clip_done()
                d.answer(0)
                d.next_question()
            d.complete()
            self.store.game_completed.assert_called_once_with()
            d.close()

    def test_show_failure_and_frozen_animation(self):
        with patch.object(LibraryDialog,'scan'):
            d=WeeklyShow(self.mod);d.setAttribute(__import__('PySide6').QtCore.Qt.WA_DeleteOnClose,False);d.ready(self.tracks);d.player.play=Mock(return_value=True);d.show();d.start_show()
            self.assertFalse(d.stage.timer.isActive());d.player.live=True;d.player.loaded=True;d.update_progress(5);self.assertTrue(d.stage.timer.isActive())
            d.hide();self.assertFalse(d.stage.timer.isActive());d.error('播放失败');d.player.finished.emit()
            self.assertFalse(d.complete);self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0],0)
            d.mod.services.act.reset_mock();d.update_progress(25);d.mod.services.act.assert_not_called();self.assertFalse(d.stage.timer.isActive());d.close()

    def test_quiz_progress_and_feedback_reset_for_next_question(self):
        with patch.object(LibraryDialog, 'scan'):
            d = GuessGame(self.mod)
            d.ready(self.tracks)
            d.player.play = Mock(return_value=True)
            d.start_game()
            d.player.progress.emit(3.5)
            self.assertEqual(d.question_progress.value(), 35)
            self.assertTrue(all(not b.property('result') for b in d.answers))
            d.clip_done()
            self.assertEqual(d.clip_clock.text(), '0:08 / 0:08')
            d.replay_clip()
            self.assertEqual(d.question_progress.value(), 0)
            d.clip_done()
            correct = d.options.index(d.current)
            wrong = (correct+1) % len(d.answers)
            d.answer(wrong)
            self.assertEqual(d.answers[correct].key.text(), '正确')
            self.assertEqual(d.answers[wrong].property('result'), 'picked')
            d.next_question()
            self.assertTrue(all(not b.property('result') for b in d.answers))
            self.assertEqual(d.question_progress.value(), 0)
            d.close()

    def test_setlist_marks_actual_track_and_keeps_long_title(self):
        with patch.object(LibraryDialog, 'scan'):
            d = WeeklyShow(self.mod)
            self.tracks[1]['title'] = '一首很长的歌名' * 18
            d.ready(self.tracks)
            d.player.play = Mock(return_value=True)
            d.show()
            d.start_show()
            d.player.finished.emit()
            self.app.processEvents()
            cells = d.program_line.cells
            self.assertEqual([f.property('cue') for f, _, _ in cells], ['done','current','next'])
            self.assertEqual(cells[1][2].toolTip(), self.tracks[1]['title'])
            self.assertLess(len(cells[1][2].text()), len(self.tracks[1]['title']))
            d.player.finished.emit()
            d.player.finished.emit()
            self.assertTrue(all(f.property('cue') == 'done' for f, _, _ in cells))
            d.close()

    def test_quiz_error_can_retry_same_clip_or_choose_again(self):
        with patch.object(LibraryDialog,'scan'):
            d=GuessGame(self.mod);d.ready(self.tracks)
            def refuse(*args):
                d.player.failed.emit('当前文件无法解码')
                return False
            d.player.play=Mock(side_effect=refuse)
            d.start_game()
            self.assertEqual(d.label.text(),'当前文件无法解码')
            self.assertIn('试听失败',d.question_title.text())
            self.assertTrue(all(not b.isEnabled() for b in d.answers))
            first=d.player.play.call_args
            d.player.play.side_effect=None
            d.relisten.click();self.assertEqual(d.player.play.call_args,first)
            self.assertIn('准备片段',d.question_title.text())
            d.player.started.emit();self.assertIn('正在试听',d.question_title.text())
            d.error('文件已移动');d.clip_done();self.assertFalse(d.clip_ready)
            d.change_tracks.click();self.assertEqual(d.questions,[])
            self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM results').fetchone()[0],0)
            d.close()

    def test_second_act_can_retry_in_place_and_only_completed_program_is_saved(self):
        with patch.object(LibraryDialog,'scan'):
            d=WeeklyShow(self.mod);d.ready(self.tracks)
            d.player.play=Mock(return_value=True);d.start_show();d.player.started.emit()
            d.player.finished.emit();self.assertEqual(d.index,1)
            self.assertIn('准备中',d.program_line.cells[1][1].text())
            second=d.player.play.call_args
            d.player.failed.emit('第二首文件无法解码')
            self.assertEqual(d.label.text(),'第二首文件无法解码')
            self.assertIn('播放失败',d.program_line.cells[1][1].text())
            self.assertTrue(d.pause_button.isHidden());self.assertTrue(d.start_button.isEnabled())
            d.player.finished.emit();self.assertEqual(d.index,1)
            d.start_button.click();self.assertEqual(d.player.play.call_args,second)
            d.player.started.emit();self.assertIn('演出中',d.program_line.cells[1][1].text())
            d.player.finished.emit();d.player.failed.emit('文件已移动')
            d.edit_button.click();self.assertEqual(d.program,[])
            self.assertTrue(all(c.isEnabled() for c in d.selectors))
            self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0],0)
            d.close()

    def test_show_uses_whole_files_and_each_files_real_duration(self):
        tracks = [dict(path=f'{i}.wav', title=title, duration=seconds)
                  for i, (title, seconds) in enumerate([('序', 4), ('主曲', 68), ('尾声', 8), ('加演', 15)])]
        with patch.object(LibraryDialog, 'scan'):
            show = WeeklyShow(self.mod)
            self.addCleanup(show.close)
            show.ready(tracks)
            self.assertTrue(show.start_button.isEnabled())
            self.assertIn('1:20', show.header.detail.text())
            show.selectors[2].setCurrentIndex(3)
            self.assertIn('1:27', show.header.detail.text())
            show.player.play = Mock()
            show.start_show()
            show.player.play.assert_called_once_with('0.wav')
            show.player.source_duration.emit(5)
            self.assertIn('0:00 / 1:28', show.header.detail.text())
            show.player.finished.emit()
            show.player.play.assert_called_with('1.wav')
            show.player.progress.emit(47)
            self.assertEqual(show.stage.elapsed, 47)
            self.assertIn('0:52 / 1:28', show.header.detail.text())
            self.assertEqual(show.progress.value(), round(52/88 * show.progress.maximum()))
            show.player.finished.emit()
            show.player.play.assert_called_with('3.wav')
            self.assertEqual(show.stage.elapsed, 0)
            self.assertIn('1:13 / 1:28', show.header.detail.text())
            show.player.finished.emit()
            self.assertTrue(show.complete)
            self.assertIn('1:28', show.header.detail.text())

    def test_short_duplicate_does_not_displace_a_playable_guess_answer(self):
        with patch.object(LibraryDialog, 'scan'):
            quiz = GuessGame(self.mod)
            self.addCleanup(quiz.close)
            short = dict(self.tracks[0], path='intro.wav', duration=3)
            duplicate = dict(self.tracks[0], path='other.mp3')
            quiz.ready([short, *self.tracks, duplicate])
            self.assertEqual(quiz.tracks, self.tracks)
            self.assertTrue(quiz.start_button.isEnabled())

    def test_failed_act_keeps_the_singer_visible_on_the_stage(self):
        with patch.object(LibraryDialog,'scan'):
            d=WeeklyShow(self.mod);d.ready(self.tracks);d.show()
            try:
                d.player.play=Mock(side_effect=lambda *a,**kw:d.player.failed.emit('文件不可读'))
                d.start_show()
                limit=time.monotonic()+3
                while stage_image('tianyi-stage').isNull() and time.monotonic()<limit:
                    self.app.processEvents();time.sleep(.005)
                self.assertFalse(stage_image('tianyi-stage').isNull())
                self.app.processEvents()
                frame=d.stage.grab().toImage()
                scenery=d.stage.backdrop.pixmap.toImage()
                # Only the singer is drawn on the left half of the idle stage.
                changed=sum(frame.pixel(x,y)!=scenery.pixel(x,y)
                            for x in range(0,frame.width()//2,4) for y in range(0,frame.height(),4))
                self.assertGreater(changed,100)
            finally:d.close()
    def tearDown(self):self.store.close()

if __name__=='__main__':unittest.main()
