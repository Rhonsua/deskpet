"""Real music widgets with isolated settings and silent, in-memory transports."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings, QProcess
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from deskpet.app import MusicPanel


class AlternatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.panels = []
        self.transports = patch('deskpet.music.audio.remote.AudioEngine.start')
        self.transports.start()
        from deskpet.music.players.bilibili_player import BilibiliPlayer
        self.start_web_process = BilibiliPlayer.start_process
        self.web_transport = patch('deskpet.music.players.bilibili_player.BilibiliPlayer.start_process')
        self.web_transport.start()
        self.panel = self.make_panel()
        self.local = []
        for name in ('第一首', '第二首'):
            song = self.root / (name + '.mp3')
            song.write_bytes(b'fixture')
            self.local.append(str(song.resolve()))
        self.panel.import_paths(self.local)
        self.web = self.panel.bilibili
        self.urls = ['https://www.bilibili.com/video/BV1xx411c7mu/',
                     'https://www.bilibili.com/video/BV1xx411c7mD/']
        self.web.tracks = [dict(url=u, title='视频' + str(i)) for i, u in enumerate(self.urls)]
        self.web.render()
        self.web.save()

    def make_panel(self):
        settings = QSettings(str(self.root / 'settings.ini'), QSettings.Format.IniFormat)
        pet = SimpleNamespace(playing=False, set_variant=lambda _: None,
            set_auto_walk=lambda _: None, toggle_walk=lambda: None,
            set_auto_teleport=lambda _: None, open_mods=lambda: None)
        panel = MusicPanel(pet, settings=settings, data_dir=self.root / 'data')
        self.panels.append(panel)
        panel.progress_timer.stop()
        panel.bilibili.watchdog.stop()
        return panel

    def tearDown(self):
        for p in self.panels:
            if p.engine:
                p.engine.shutdown()
            p.store.close()
            p.hide()
            p.deleteLater()
        self.app.processEvents()
        self.transports.stop()
        self.web_transport.stop()
        self.temp.cleanup()

    def end_local(self):
        self.panel.player.values.update(state=0, status=7, duration=10000, position=10000)
        self.panel.media_changed(QMediaPlayer.MediaStatus.EndOfMedia)

    def end_web(self):
        self.web.handle_event(dict(type='state', token=self.web.latch.token,
            ended=True, seen_playing=True, playing=False, position=10, duration=10))

    def test_alternates_both_sources_and_wraps_without_changing_modes(self):
        p = self.panel
        p.set_alternating(True)
        p.play_row(0)
        for expected_web, expected_local in ((0, 1), (1, 0), (0, 1)):
            self.end_local()
            self.assertEqual(p.playback_source, 'web')
            self.assertEqual(self.web.current_url, self.urls[expected_web])
            self.assertTrue(self.web.pending_load['background'])
            self.assertFalse(p.autoplay_requested)
            token = self.web.latch.token
            self.end_web()
            self.assertEqual(p.playback_source, 'local')
            self.assertEqual(p.current_path(), self.local[expected_local])
            self.assertFalse(self.web.active)
            self.web.handle_event(dict(type='state', token=token, ended=True, seen_playing=True))
            self.assertEqual(p.current_path(), self.local[expected_local])
        self.assertEqual(p.queue.mode, 'order')
        self.assertEqual(self.web.queue.mode, 'order')

    def test_next_and_previous_work_from_both_control_surfaces(self):
        p = self.panel
        p.set_alternating(True)
        p.play_row(0)
        p.step(1)
        self.assertEqual(self.web.current_url, self.urls[0])
        self.web.step(1)
        self.assertEqual(p.current_path(), self.local[1])
        p.step(-1)
        self.assertEqual(p.playback_source, 'web')
        self.web.step(-1)
        self.assertEqual(p.current_path(), self.local[0])
        self.assertEqual(p.playback_source, 'local')
        p.step(1)
        self.assertEqual(self.web.current_url, self.urls[0])
        p.step(1)
        self.assertEqual(p.current_path(), self.local[1])

    def test_web_reverse_direction_is_used_while_alternating(self):
        p = self.panel
        self.web.reverse_toggle.setChecked(True)
        p.set_alternating(True)
        p.play_row(0)
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[-1])
        self.end_web()
        self.assertEqual(p.current_path(), self.local[1])
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[0])
        self.end_web()
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[-1])

    def test_reorder_during_alternation_uses_song_identity(self):
        p = self.panel
        p.set_alternating(True)
        self.web.play_row(0)
        self.web.move_song(1)
        self.assertEqual(self.web.current_url, self.urls[0])
        self.end_web()
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[1])

    def test_local_reverse_starts_at_end_stops_at_front_and_loops(self):
        p = self.panel
        p.reverse_toggle.setChecked(True)
        self.assertFalse(self.web.queue.reverse)
        p.play_active_playlist()
        self.assertEqual(p.current_path(), self.local[1])
        self.end_local()
        self.assertEqual(p.current_path(), self.local[0])
        self.end_local()
        self.assertFalse(p.autoplay_requested)
        p.mode_choice.setCurrentIndex(p.mode_choice.findData('loop'))
        p.play_row(0)
        self.end_local()
        self.assertEqual(p.current_path(), self.local[1])

    def test_local_reverse_uses_last_visible_song_without_selection(self):
        p = self.panel
        p.reverse_toggle.setChecked(True)
        p.search.setText('第一首')
        p.play_active_playlist()
        self.assertEqual(p.current_path(), self.local[0])
        p.search.setText('不存在的歌曲')
        p.play_active_playlist()
        self.assertIn('没有可播放', p.status.text())

    def test_local_reorder_preserves_position_shuffle_and_saved_current_queue(self):
        p = self.panel
        p.play_row(0)
        p.pending_seek = None
        p.player.values.update(position=42000, duration=100000, state=1)
        p.mode_choice.setCurrentIndex(p.mode_choice.findData('shuffle'))
        p.queue.bag, p.queue.history = [1], [1]
        with patch.object(p.engine, 'send') as send:
            p.move_down_button.click()
            p.reverse_toggle.setChecked(True)
        send.assert_not_called()
        self.assertEqual(p.current_path(), self.local[0])
        self.assertEqual(p.player.position(), 42000)
        self.assertTrue(p.autoplay_requested)
        self.assertEqual(p.paths, list(reversed(self.local)))
        self.assertEqual(p.queue.index, 1)
        self.assertEqual(p.queue.bag, [0])
        self.assertEqual(p.queue.history, [0])
        self.assertFalse(p.move_down_button.isEnabled())
        self.assertFalse(p.reverse_toggle.isEnabled())
        reopened = self.make_panel()
        self.assertEqual(reopened.paths, list(reversed(self.local)))
        self.assertEqual(reopened.queue.paths, p.queue.paths)
        self.assertEqual(reopened.current_path(), self.local[0])
        self.assertEqual(reopened.pending_seek, 42000)
        self.assertTrue(reopened.reverse_toggle.isChecked())
        self.assertFalse(reopened.bilibili.reverse_toggle.isChecked())
        self.assertIsNone(reopened._player)

    def test_local_move_boundaries_and_editing_another_playlist(self):
        p = self.panel
        self.assertFalse(p.move_up_button.isEnabled())
        self.assertFalse(p.move_down_button.isEnabled())
        p.play_row(0)
        p.move_song(-1)
        self.assertEqual(p.paths, self.local)
        self.assertFalse(p.move_up_button.isEnabled())
        old_queue = p.queue.paths[:]
        old_owner = p.queue_owner
        p.library.create('另一歌单')
        p.library.add(self.local)
        p.render_library()
        p.move_song(1)
        self.assertEqual(p.paths, list(reversed(self.local)))
        self.assertEqual(p.queue.paths, old_queue)
        self.assertEqual(p.queue_owner, old_owner)
        self.assertEqual(p.current_path(), self.local[0])

    def test_each_source_keeps_its_direction_in_alternation(self):
        p = self.panel
        song = self.root / '第三首.mp3'
        song.write_bytes(b'fixture')
        p.import_paths([str(song)])
        p.reverse_toggle.setChecked(True)
        p.set_alternating(True)
        self.web.play_row(0)
        self.end_web()
        self.assertEqual(p.current_path(), str(song))
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[1])
        self.end_web()
        self.assertEqual(p.current_path(), self.local[1])
        self.end_local()
        self.assertEqual(self.web.current_url, self.urls[0])
        self.end_web()
        self.assertEqual(p.current_path(), self.local[0])
        self.assertFalse(self.web.queue.reverse)

    def test_local_reorder_during_alternation_keeps_next_song_identity(self):
        p = self.panel
        p.set_alternating(True)
        p.play_row(0)
        p.move_song(1)
        self.end_local()
        self.end_web()
        self.assertEqual(p.current_path(), self.local[1])

    def test_chat_default_play_respects_each_reverse_setting(self):
        from deskpet.chat.music_actions import _play_default
        p = self.panel
        p.reverse_toggle.setChecked(True)
        _play_default(p, 'local')
        self.assertEqual(p.current_path(), self.local[1])
        self.web.reverse_toggle.setChecked(True)
        _play_default(p, 'web')
        self.assertEqual(self.web.current_url, self.urls[1])

    def test_local_reverse_changes_do_not_send_playback_commands(self):
        p = self.panel
        p.play_row(0)
        with patch.object(p.engine, 'send') as send:
            p.reverse_toggle.setChecked(True)
            p.reverse_toggle.setChecked(False)
        send.assert_not_called()
        self.assertEqual(p.current_path(), self.local[0])

    def test_empty_and_missing_local_files_fall_back_to_web(self):
        p = self.panel
        p.set_alternating(True)
        self.web.play_row(0)
        for path in self.local:
            Path(path).unlink()
        self.end_web()
        self.assertEqual(p.playback_source, 'web')
        self.assertEqual(self.web.current_url, self.urls[1])
        self.assertIsNone(p._player)

    def test_empty_web_loops_local_and_disabled_restores_order_stop(self):
        p = self.panel
        self.web.tracks = []
        p.set_alternating(True)
        p.play_row(1)
        self.end_local()
        self.assertEqual(p.current_path(), self.local[0])
        p.alternate_toggle.setChecked(False)
        self.assertFalse(self.web.alternate_toggle.isChecked())
        p.play_row(1)
        self.end_local()
        self.assertFalse(p.autoplay_requested)
        self.assertEqual(p.status.text(), '这个歌单听完啦')

    def test_pause_and_late_end_do_not_switch_source(self):
        p = self.panel
        p.set_alternating(True)
        p.play_row(0)
        p.autoplay_requested = False
        self.end_local()
        self.assertEqual(p.playback_source, 'local')
        self.assertFalse(self.web.active)

    def test_restart_restores_sources_cursors_and_stays_lazy(self):
        p = self.panel
        p.set_alternating(True)
        p.play_row(0)
        self.end_local()
        p.save()
        reopened = self.make_panel()
        self.assertTrue(reopened.alternating.enabled)
        self.assertEqual(reopened.playback_source, 'web')
        self.assertEqual(reopened.bilibili.list.currentRow(), 0)
        self.assertEqual(reopened.bilibili.current_url, self.urls[0])
        self.assertIsNone(reopened._player)
        self.assertFalse(reopened.bilibili.active)
        self.assertEqual(reopened.bilibili.process.state(), QProcess.ProcessState.NotRunning)
        reopened.toggle()
        self.assertEqual(reopened.bilibili.pending_load['url'], self.urls[0])
        self.assertTrue(reopened.bilibili.pending_load['background'])
        reopened.step(1)
        self.assertEqual(reopened.current_path(), self.local[1])

    def test_restored_old_queue_does_not_override_selected_playlist(self):
        p = self.panel
        p.play_row(0)
        old_owner = p.queue_owner
        p.library.create('另一份歌单')
        p.library.add([self.local[1]])
        p.render_library()
        p.save()
        reopened = self.make_panel()
        self.assertEqual(reopened.queue_owner, old_owner)
        self.assertNotEqual(reopened.queue_owner, reopened.library.active_id)
        reopened.play_button.click()
        self.assertEqual(reopened.current_path(), self.local[1])
        self.assertEqual(reopened.queue_owner, reopened.library.active_id)

    def test_new_selection_and_explicit_playlist_button_override_old_song(self):
        p = self.panel
        p.play_row(0)
        p.list.setCurrentRow(1)
        p.list.itemClicked.emit(p.list.item(1))
        p.play_button.click()
        self.assertEqual(p.current_path(), self.local[1])
        self.web.play_row(0)
        p.play_active_playlist()
        self.assertEqual(p.playback_source, 'local')
        self.assertEqual(p.current_path(), self.local[1])

    def test_invalid_saved_position_and_queue_are_recoverable(self):
        p = self.panel
        p.play_row(0)
        p.settings.setValue('current_position', 'not-a-number')
        p.settings.setValue('current_queue', '{"wrong": true}')
        reopened = self.make_panel()
        self.assertEqual(reopened.pending_seek, 0)
        self.assertEqual(reopened.current_path(), self.local[0])

    def test_saved_end_position_rewinds_before_playing(self):
        p = self.panel
        p.play_row(0)
        p.settings.setValue('current_position', 10000)
        reopened = self.make_panel()
        reopened.ensure_audio()
        reopened.player.values.update(duration=10000, status=2, seekable=True)
        reopened.duration_changed(10000)
        self.assertIsNone(reopened.pending_seek)
        self.assertEqual(reopened.engine.pending[-1], {'cmd': 'seek', 'position': 0})

    def test_web_toggle_during_cold_start_is_delivered_with_load(self):
        self.web.play_row(0)
        self.web.toggle()
        self.assertFalse(self.web.pending_load['autoplay'])
        self.web.toggle()
        self.assertTrue(self.web.pending_load['autoplay'])
        with patch.object(self.web, 'send') as send:
            self.web.handle_event({'type': 'ready'})
            self.assertTrue(send.call_args.args[0]['autoplay'])
            self.assertEqual(send.call_args.args[0]['url'], self.urls[0])
            with patch.object(self.web.process, 'state', return_value=QProcess.ProcessState.Running):
                self.web.toggle()
                self.assertEqual(send.call_args.args[0], {'cmd': 'pause'})

    def test_web_pause_wins_over_late_end_report(self):
        self.panel.set_alternating(True)
        self.web.play_row(0)
        self.web.set_playing(False)
        self.web.handle_event(dict(type='state', token=self.web.latch.token,
            requested_play=True, ended=True, seen_playing=True, playing=False))
        self.assertEqual(self.panel.playback_source, 'web')
        self.assertFalse(self.web.latch.completed)
        self.assertIsNone(self.panel._player)

    def test_browsed_web_selection_plays_selected_instead_of_resuming_old(self):
        self.web.play_row(0)
        self.web.list.setCurrentRow(1)
        self.web.toggle()
        self.assertEqual(self.web.current_url, self.urls[1])

    def test_enabling_alternation_hides_active_window_and_pending_load(self):
        self.web.play_row(0)
        self.assertFalse(self.web.pending_load['background'])
        with patch.object(self.web, 'send') as send:
            self.panel.set_alternating(True)
            send.assert_called_once_with({'cmd': 'hide'})
        self.assertTrue(self.web.pending_load['background'])

    def test_background_launch_is_used_for_cold_start_and_worker_restart(self):
        self.panel.set_alternating(True)
        self.web.play_row(0)
        with patch.object(self.web.process, 'start'):
            # Exercise the real launch method without starting a browser here.
            self.web.start_process = lambda: self.start_web_process(self.web)
            self.web.start_process()
            self.assertIn('--start-hidden', self.web.process.arguments())
            self.web.process_finished()
            self.assertIn('--start-hidden', self.web.process.arguments())
            self.assertTrue(self.web.hidden)

    def test_existing_worker_receives_background_flag_when_switching_tracks(self):
        self.panel.set_alternating(True)
        self.web.ready = True
        with patch.object(self.web.process, 'state', return_value=QProcess.ProcessState.Running), \
                patch.object(self.web, 'send') as send:
            self.web.play_row(1)
            self.assertTrue(send.call_args.args[0]['background'])
            self.assertEqual(send.call_args.args[0]['url'], self.urls[1])


if __name__ == '__main__':
    unittest.main()
