"""Rhythm input and lifecycle regression tests; audio stays muted."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer
from deskpet.mods.bond.chart import generate, validate, Judgement
from deskpet.mods.bond.rhythm import RhythmGame


def example():
    chart=generate({},seed=0)
    chart['notes']=[dict(id='a',type='tap',lane=0,at=1.,end=1.),
                    dict(id='b',type='hold',lane=1,at=2.,end=4.)]
    return chart


class ChartTests(unittest.TestCase):
    def test_same_seed_replays_and_different_seed_changes_chart(self):
        a=generate({},seed=2);b=generate({},seed=2);c=generate({},seed=3)
        self.assertEqual(a,b);self.assertNotEqual(a['notes'],c['notes'])
        self.assertTrue(any(n['type']=='hold' for n in a['notes']))

    def test_music_features_generate_playable_input_modes(self):
        analysis=dict(beats_ms=list(range(0,90000,500)),onsets_ms=list(range(100,90000,350)),sustain_regions_ms=[[1000,80000]])
        for mode in ('mouse','keyboard'):
            for lanes in (3,4):
                for difficulty in ('easy','normal','hard'):
                    for seed in range(8):
                        chart=generate(analysis,offset=15,duration=60,input_mode=mode,lanes=lanes,difficulty=difficulty,seed=seed)
                        validate(chart);self.assertFalse(chart['practice'])

    def test_hold_tail_double_press_and_normalized_score(self):
        j=Judgement(example())
        self.assertEqual(j.press(0,1),'完美');self.assertEqual(j.press(0,1),'')
        j.release(0,1.1);j.press(1,2);j.advance(3);j.release(1,4);j.advance(6)
        self.assertEqual((j.score,j.holds,j.hits,j.perfect),(1000000,1,2,2))

    def test_early_release_and_unpressed_hold_miss_once(self):
        j=Judgement(example());j.press(1,2);j.release(1,3);j.advance(3.1);score=j.score
        j.press(1,3.2);j.advance(10);j.advance(20)
        self.assertEqual(j.misses,2);self.assertEqual(j.score,score);self.assertLess(score,500000)

    def test_hold_pause_requires_rearming_without_counting_pause_time(self):
        j=Judgement(example());j.press(0,1);j.release(0,1.1);j.press(1,2);j.suspend(3)
        j.held={1};j.rearm();j.advance(4)
        self.assertEqual(j.score,1000000)
        j=Judgement(example());j.press(1,2);j.suspend(3);j.rearm();j.advance(3.1)
        self.assertEqual(j.misses,2)


class RhythmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.mod=SimpleNamespace(active=True,store=SimpleNamespace(stage=0,preference=lambda k,d:d,configure=Mock(),best=lambda _: (10,1)),
            finish_round=Mock(),games=[],services=SimpleNamespace(
                snapshot=Mock(return_value={'playing':False,'volume':0,'beats':{},'beat_source':''}),act=Mock(),
                audio_claim=Mock(return_value='lease'),audio_valid=lambda _:True,audio_release=Mock()))
        self.game=RhythmGame(self.mod,chart=generate({},seed=2))
        self.game.setAttribute(Qt.WA_DeleteOnClose,False);self.game.sound.setChecked(False)
        self.addCleanup(self.game.close)

    def test_existing_song_is_not_interrupted(self):
        self.mod.services.snapshot.return_value['playing']=True;self.game.start()
        self.assertFalse(self.game.requested);self.assertIn('先暂停',self.game.label.text())

    def test_close_ignores_loaded_and_releases_lease(self):
        self.game.start();self.game.close()
        with patch.object(self.game.player,'play') as play:
            self.game.loaded(QMediaPlayer.LoadedMedia);play.assert_not_called()
        self.assertFalse(self.game.timer.isActive());self.mod.services.audio_release.assert_called_once()
        self.mod.finish_round.assert_not_called()

    def test_completion_once_after_full_round_and_sufficient_hits(self):
        self.game.start();self.game.round.hits=5
        self.game.started=time.monotonic()-40.1
        self.game.update_game();self.game.update_game();self.mod.finish_round.assert_called_once()

    def test_no_hit_and_early_stop_get_no_growth(self):
        self.game.start();self.game.started=time.monotonic()-40.1;self.game.update_game()
        self.mod.finish_round.assert_not_called()

    def test_loading_timeout_does_not_restart(self):
        self.game.requested=True;self.game.loading_timeout();self.assertTrue(self.game.finished)
        self.mod.active=False
        with patch.object(self.game.player,'play') as play:
            self.game.loaded(QMediaPlayer.LoadedMedia);play.assert_not_called()

    def test_source_round_uses_audio_position_not_wall_time(self):
        self.game.start();self.game.source='virtual-song.mp3';self.game.offset=30
        self.game.started=time.monotonic()-200
        with patch.object(self.game.player,'position',return_value=32000),patch.object(self.game.player,'playbackState',return_value=QMediaPlayer.PlayingState):self.game.update_game()
        self.assertEqual(self.game.elapsed,2);self.assertFalse(self.game.finished)

    def test_pause_freezes_round_and_other_music_still_cancels(self):
        self.game.start();self.game.pause();elapsed=self.game.round.elapsed
        self.game.started-=15;self.game.update_game();self.assertEqual(self.game.round.elapsed,elapsed)
        self.mod.services.snapshot.return_value['playing']=True;self.game.update_game()
        self.assertTrue(self.game.finished);self.mod.finish_round.assert_not_called()


if __name__=='__main__':unittest.main()
