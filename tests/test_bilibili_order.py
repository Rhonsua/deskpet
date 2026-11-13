"""Reordering and reverse play use temporary settings and never open a browser."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget
from deskpet.music.players.bilibili_player import BilibiliPlayer


class BilibiliOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.owner = QWidget()
        self.owner.settings = QSettings(str(Path(self.temp.name) / 'settings.ini'), QSettings.Format.IniFormat)
        self.owner.volume = Mock()
        self.owner.volume.value.return_value = 60
        self.owner.set_alternating = Mock()
        self.web = BilibiliPlayer(self.owner)
        self.web.watchdog.stop()
        self.web.start_process = Mock()
        self.urls = [f'https://www.bilibili.com/video/BV{n:010d}/' for n in range(1, 4)]
        self.web.tracks = [dict(url=url, title=f'歌曲 {i+1}') for i, url in enumerate(self.urls)]
        self.web.render()

    def tearDown(self):
        self.owner.close()
        self.owner.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_moving_playing_track_preserves_transport_position_and_selection(self):
        web = self.web
        web.play_row(1)
        web.playing = True
        web.metrics = dict(position=32, duration=120)
        before_load, token = web.pending_load, web.latch.token
        web.start_process.reset_mock()
        with patch.object(web, 'send') as send:
            web.move_up_button.click()
            web.move_down_button.click()
            web.move_down_button.click()
        send.assert_not_called()
        web.start_process.assert_not_called()
        self.assertEqual(web.current_url, self.urls[1])
        self.assertEqual(web.list.currentRow(), 2)
        self.assertEqual(web.queue.index, 2)
        self.assertEqual(web.queue.paths, [self.urls[0], self.urls[2], self.urls[1]])
        self.assertIs(web.pending_load, before_load)
        self.assertEqual(web.latch.token, token)
        self.assertEqual(web.metrics['position'], 32)
        self.assertTrue(web.playing)
        self.assertFalse(web.move_down_button.isEnabled())

    def test_moving_other_track_keeps_current_song_and_next_tracks_new_order(self):
        web = self.web
        web.play_row(1)
        web.list.setCurrentRow(2)
        web.move_song(-1)
        self.assertEqual(web.current_url, self.urls[1])
        self.assertEqual(web.queue.index, 2)
        self.assertEqual(web.list.currentRow(), 1)
        web.reverse_toggle.setChecked(True)
        web.step(1)
        self.assertEqual(web.current_url, self.urls[2])

    def test_reverse_without_selection_starts_at_end_and_stops_at_front(self):
        web = self.web
        web.reverse_toggle.setChecked(True)
        web.toggle()
        self.assertEqual(web.current_url, self.urls[-1])
        for index in (1, 0):
            web.handle_event(dict(type='state', token=web.latch.token, ended=True, seen_playing=True, playing=False))
            self.assertEqual(web.current_url, self.urls[index])
        with patch.object(web, 'send'):
            web.handle_event(dict(type='state', token=web.latch.token, ended=True, seen_playing=True, playing=False))
        self.assertFalse(web.active)

    def test_direction_change_does_not_restart_and_remembers_across_shuffle_and_restart(self):
        web = self.web
        web.play_row(1)
        web.start_process.reset_mock()
        with patch.object(web, 'send') as send:
            web.reverse_toggle.setChecked(True)
            web.move_song(-1)
            web.mode.setCurrentIndex(web.mode.findData('shuffle'))
            self.assertFalse(web.reverse_toggle.isEnabled())
            self.assertTrue(web.reverse_toggle.isChecked())
            web.mode.setCurrentIndex(web.mode.findData('loop'))
        send.assert_not_called()
        web.start_process.assert_not_called()
        restored = BilibiliPlayer(self.owner)
        restored.watchdog.stop()
        self.assertTrue(restored.reverse_toggle.isChecked())
        self.assertTrue(restored.reverse_toggle.isEnabled())
        self.assertEqual(restored.queue.mode, 'loop')
        self.assertEqual([t['url'] for t in restored.tracks], [self.urls[1], self.urls[0], self.urls[2]])
        self.assertEqual(restored.current_url, self.urls[1])
        self.assertEqual(restored.queue.index, 0)
        self.assertFalse(restored.active)

    def test_move_boundaries_empty_and_selection(self):
        web = self.web
        self.assertFalse(web.move_up_button.isEnabled())
        self.assertFalse(web.move_down_button.isEnabled())
        web.move_song(1)
        self.assertEqual([t['url'] for t in web.tracks], self.urls)
        web.list.setCurrentRow(0)
        self.assertFalse(web.move_up_button.isEnabled())
        web.move_song(-1)
        self.assertEqual([t['url'] for t in web.tracks], self.urls)
        web.tracks.clear()
        web.render()
        web.move_song(1)
        self.assertFalse(web.move_down_button.isEnabled())


if __name__ == '__main__':
    unittest.main()
