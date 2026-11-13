import unittest

from deskpet.music.players.web_playback_guard import TailCompletion, ReplayRecovery


def report(**changes):
    return dict(token='one', media_id=1, has_video=True, position=99.94,
                duration=100, seen_playing=True, playing=False, paused=True,
                seeking=False, ready_state=4, buffered_to_end=True, error=0,
                **changes)


class TailTests(unittest.TestCase):
    def test_missing_end_event_at_buffered_tail(self):
        guard = TailCompletion()
        value = report()
        self.assertFalse(guard.update(value, 1, True))
        self.assertFalse(guard.update(value, 4.9, True))
        self.assertTrue(guard.update(value, 5, True))

    def test_pause_buffering_seeking_loading_or_midtrack_never_complete(self):
        for changes in ({'position': 80}, {'seeking': True}, {'ready_state': 2},
                        {'buffered_to_end': False}, {'error': 3},
                        {'seen_playing': False}, {'duration': 0}, {'has_video': False}):
            with self.subTest(changes=changes):
                guard = TailCompletion()
                value = report()
                value.update(changes)
                self.assertFalse(guard.update(value, 0, True))
                self.assertFalse(guard.update(value, 10, True))
        guard = TailCompletion()
        guard.update(report(), 0, True)
        self.assertFalse(guard.update(report(), 10, False))
        self.assertFalse(guard.update(report(), 11, True))

    def test_duration_revision_track_or_media_replacement_resets_deadline(self):
        for changes in ({'token': 'two'}, {'media_id': 2},
                        {'duration': 99.96}, {'position': 99.98}):
            with self.subTest(changes=changes):
                guard = TailCompletion()
                guard.update(report(), 0, True)
                value = report()
                value.update(changes)
                self.assertFalse(guard.update(value, 5, True))
                self.assertTrue(guard.update(value, 9, True))


class ReplayTests(unittest.TestCase):
    def test_delayed_history_restore_resumes_without_repeating_intro(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(duration=210, position=.1, playing=True, paused=False)
        guard.update(value, .1)
        self.assertTrue(guard.active)
        self.assertFalse(guard.blocking)
        value.update(position=207, ended=True)
        self.assertEqual(guard.update(value, 1.5), 'restore')
        self.assertAlmostEqual(guard.target, 1.5)
        self.assertTrue(guard.blocking)
        value.update(position=1.6, ended=False)
        guard.update(value, 2)
        self.assertFalse(guard.blocking)
        value.update(position=2.6)
        guard.update(value, 3)
        self.assertFalse(guard.blocking)

    def test_continuous_playback_and_natural_end_are_not_rewound(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(duration=4, position=.1, playing=True, paused=False)
        guard.update(value, .1)
        for now in (1, 2, 3):
            value.update(position=now)
            self.assertIsNone(guard.update(value, now))
            self.assertFalse(guard.blocking)
        value.update(position=4, ended=True, playing=False)
        self.assertIsNone(guard.update(value, 4))
        self.assertFalse(guard.active)

    def test_manual_seek_cancels_opening_history_protection(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(position=.1, playing=True)
        guard.update(value, .1)
        guard.cancel()
        value.update(position=99)
        self.assertIsNone(guard.update(value, 1))

    def test_opening_at_remembered_tail_never_confirms_start(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(duration=210, position=207, playing=True)
        self.assertEqual(guard.update(value, 2), 'restart')
        self.assertTrue(guard.blocking)

    def test_stuck_seek_retries_then_one_reload(self):
        guard = ReplayRecovery()
        guard.start(0)
        self.assertIsNone(guard.update(report(), 1))
        for now in (2, 4, 6):
            self.assertEqual(guard.update(report(), now), 'restart')
        self.assertEqual(guard.update(report(), 8), 'reload')
        self.assertIsNone(guard.update(report(), 20))

    def test_only_playing_at_beginning_confirms_replay(self):
        guard = ReplayRecovery()
        guard.start(0)
        value = report()
        value.update(position=.1)
        guard.update(value, 1)
        self.assertTrue(guard.active)
        value.update(playing=True, paused=False, seeking=True)
        guard.update(value, 1)
        self.assertTrue(guard.active)
        value['seeking'] = False
        guard.update(value, 1)
        self.assertFalse(guard.active)

    def test_explicit_pause_cancels_recovery(self):
        guard = ReplayRecovery()
        guard.start(0)
        guard.cancel()
        self.assertIsNone(guard.update(report(), 30))

    def test_slow_first_report_after_successful_seek_does_not_rewind(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(position=3.4, playing=True, paused=False, restart_settled=True)
        self.assertIsNone(guard.update(value, 3.5))
        self.assertFalse(guard.blocking)
        for now in (4.5, 6.5, 8.5):
            value['position'] = now - .1
            self.assertIsNone(guard.update(value, now))
        self.assertEqual(guard.attempts, 0)

    def test_lost_seek_ack_but_observed_start_never_repeats_intro(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=4.2, playing=True, paused=False,
                     restart_settled=False, restart_observed=True, restart_elapsed=4.3)
        self.assertIsNone(guard.update(value, 4.4))
        self.assertTrue(guard.has_played)
        self.assertFalse(guard.blocking)
        self.assertEqual(guard.attempts, 0)

    def test_zero_seen_while_buffering_confirms_later_without_seek_ack(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=.1, ready_state=1, restart_settled=False)
        guard.update(value, .1)
        value.update(position=4.2, ready_state=4, playing=True, paused=False)
        self.assertIsNone(guard.update(value, 4.3))
        self.assertFalse(guard.blocking)
        self.assertEqual(guard.attempts, 0)

    def test_delayed_ipc_samples_do_not_look_like_a_history_jump(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=.1, playing=True, paused=False, sample_clock=10)
        guard.update(value, 3)  # This report spent nearly three seconds in transit.
        value.update(position=3.7, sample_clock=13.6)
        self.assertIsNone(guard.update(value, 3.7))
        self.assertFalse(guard.blocking)
        self.assertEqual(guard.attempts, 0)

    def test_small_player_clock_catchup_is_not_a_seek(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=.1, playing=True, paused=False)
        guard.update(value, .1)
        value.update(position=3)
        self.assertIsNone(guard.update(value, 1))
        self.assertEqual(guard.attempts, 0)

    def test_late_report_after_protection_expires_cannot_seek(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=.1, playing=True, paused=False)
        guard.update(value, .1)
        value.update(position=60)
        self.assertIsNone(guard.update(value, 30))
        self.assertFalse(guard.active)

    def test_old_media_evidence_cannot_hide_a_real_history_jump(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = dict(report(), position=.1, playing=True, paused=False, sample_clock=1)
        guard.update(value, .1)
        value.update(position=90, sample_clock=100, media_id=2)
        self.assertEqual(guard.update(value, 1), 'restore')
        self.assertAlmostEqual(guard.target, 1)

    def test_buffering_or_pending_seek_does_not_repeat_the_beginning(self):
        for waiting in ({'seeking': True}, {'ready_state': 1}, {'duration': 0}, {'has_video': False}):
            with self.subTest(waiting=waiting):
                guard = ReplayRecovery()
                guard.start(0)
                value = report()
                value.update(waiting)
                for now in (2, 4, 6, 8, 20):
                    self.assertIsNone(guard.update(value, now))
                self.assertEqual(guard.attempts, 0)
        guard = ReplayRecovery()
        guard.start(0)
        value = report()
        value.update(position=.1)
        for now in (2, 4, 6, 8):
            self.assertIsNone(guard.update(value, now))

    def test_repeated_site_history_jumps_preserve_progress(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(playing=True, paused=False, position=.1)
        guard.update(value, .1)
        for now in (3, 6, 9):
            value.update(position=95, ended=True)
            self.assertEqual(guard.update(value, now), 'restore')
            self.assertAlmostEqual(guard.target, now)
            value.update(position=now + .1, ended=False)
            self.assertIsNone(guard.update(value, now + .1))
        value.update(position=95, ended=True)
        self.assertEqual(guard.update(value, 12), 'failed')
        self.assertFalse(guard.active)  # No reload back to zero after audio played.

    def test_transient_missing_metadata_does_not_erase_playback_progress(self):
        guard = ReplayRecovery()
        guard.start(0, settle_for=15)
        value = report()
        value.update(playing=True, paused=False, position=.1)
        guard.update(value, .1)
        value.update(position=3)
        guard.update(value, 3)
        waiting = dict(value, position=0, duration=0, ready_state=0)
        self.assertIsNone(guard.update(waiting, 3.5))
        value.update(position=4)
        self.assertIsNone(guard.update(value, 4))
        self.assertEqual(guard.attempts, 0)

    def test_short_clip_remembered_tail_without_seek_ack_is_not_a_start(self):
        guard = ReplayRecovery()
        guard.start(0)
        value = report()
        value.update(duration=3, position=1.9, playing=True, paused=False)
        self.assertEqual(guard.update(value, 2), 'restart')

    def test_reloaded_page_cannot_create_reload_loop(self):
        guard = ReplayRecovery()
        guard.start(0, allow_reload=False)
        for now in (2, 4, 6):
            self.assertEqual(guard.update(report(), now), 'restart')
        self.assertEqual(guard.update(report(), 8), 'failed')
        self.assertIsNone(guard.update(report(), 20))


if __name__ == '__main__':
    unittest.main()
