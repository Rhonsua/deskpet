import unittest

from web_playback_guard import TailCompletion, ReplayRecovery


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

    def test_reloaded_page_cannot_create_reload_loop(self):
        guard = ReplayRecovery()
        guard.start(0, allow_reload=False)
        for now in (2, 4, 6):
            self.assertEqual(guard.update(report(), now), 'restart')
        self.assertEqual(guard.update(report(), 8), 'failed')
        self.assertIsNone(guard.update(report(), 20))


if __name__ == '__main__':
    unittest.main()
