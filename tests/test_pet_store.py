import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from pet_store import PetStore


class PetStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'pet.db'
        self.store = PetStore(self.path)
        self.start = datetime(2026, 10, 17, 12)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def listen(self, seconds, reward=True, start=None):
        start = start or self.start
        for offset in range(0, seconds, 5):
            amount = min(5, seconds - offset)
            self.store.record('song.mp3', amount, reward,
                              start + timedelta(seconds=offset + amount))

    def test_five_minutes_and_daily_cap(self):
        self.listen(300)
        self.assertEqual((self.store.pet()['notes'], self.store.pet()['xp']), (22, 15))
        self.listen(15000, start=self.start + timedelta(seconds=300))
        pet = self.store.pet()
        self.assertEqual(pet['notes'], 120)
        self.assertEqual(self.store.stats(self.start)['today'], 15300)
        self.assertEqual(self.store.db.execute('SELECT SUM(xp) FROM ledger').fetchone()[0], 260)

    def test_muted_counts_without_rewards(self):
        self.listen(300, reward=False)
        self.assertEqual(self.store.stats(self.start)['today'], 300)
        self.assertEqual(self.store.pet()['notes'], 20)
        self.assertEqual(self.store.pet()['progress'], 0)

    def test_reward_status_tracks_earned_notes_not_balance(self):
        self.assertEqual(self.store.stats(self.start)['reward_remaining'], 300)
        self.listen(420)
        self.store.feed('小包子', self.start + timedelta(seconds=421))
        stats = self.store.stats(self.start)
        self.assertEqual(stats['reward_notes'], 2)
        self.assertEqual(stats['reward_limit'], 100)
        self.assertEqual(stats['reward_remaining'], 180)
        self.assertEqual(self.store.pet()['notes'], 14)
        self.listen(300, reward=False, start=self.start + timedelta(seconds=425))
        self.assertEqual(self.store.stats(self.start)['reward_remaining'], 180)

    def test_daily_cap_resets_after_midnight_without_restart(self):
        self.listen(15000)
        self.assertIsNone(self.store.stats(self.start)['reward_remaining'])
        self.listen(3600, start=self.start + timedelta(seconds=15000))
        self.assertEqual(self.store.pet()['notes'], 120)
        self.assertEqual(self.store.stats(self.start)['today'], 18600)
        tomorrow = self.start + timedelta(days=1)
        self.assertEqual(self.store.stats(tomorrow)['reward_notes'], 0)
        self.assertEqual(self.store.stats(tomorrow)['reward_remaining'], 300)
        self.listen(300, start=tomorrow)
        self.assertEqual(self.store.pet()['notes'], 122)
        self.assertEqual(self.store.stats(tomorrow)['reward_notes'], 2)
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 100)

    def test_existing_old_cap_can_keep_earning_after_update(self):
        self.listen(7200)
        self.store.close()
        self.store = PetStore(self.path)
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 48)
        self.assertEqual(self.store.stats(self.start)['reward_remaining'], 300)
        self.listen(300, start=self.start + timedelta(seconds=7200))
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 50)

    def test_restart_retains_partial_reward(self):
        self.listen(295)
        self.store.close()
        self.store = PetStore(self.path)
        self.store.record('song.mp3', 5, True, self.start + timedelta(seconds=300))
        self.assertEqual(self.store.pet()['notes'], 22)
        self.assertEqual(self.store.pet()['progress'], 0)

    def test_midnight_split(self):
        self.store.record('song.mp3', 4, True, datetime(2026, 10, 18, 0, 0, 2))
        rows = self.store.db.execute('SELECT day,seconds FROM daily ORDER BY day').fetchall()
        self.assertEqual([(r['day'], r['seconds']) for r in rows],
                         [('2026-10-17', 2), ('2026-10-18', 2)])

    def test_feed_cooldown_and_fullness(self):
        ok, _ = self.store.feed('小包子', self.start)
        self.assertTrue(ok)
        self.assertEqual(self.store.pet()['notes'], 12)
        self.assertFalse(self.store.feed('小包子', self.start + timedelta(seconds=2))[0])
        self.assertTrue(self.store.feed('小包子', self.start + timedelta(seconds=11))[0])
        self.assertEqual(self.store.pet()['hunger'], 100)
        self.assertFalse(self.store.feed('小包子', self.start + timedelta(seconds=22))[0])

    def test_sleep_gap_ignored(self):
        self.store.record('song.mp3', 3600)
        self.store.tick_running(3600)
        self.assertEqual(self.store.stats(self.start)['total'], 0)
        self.assertEqual(self.store.pet()['hunger'], 70)

    def test_hunger_declines_only_with_runtime(self):
        for _ in range(360):
            self.store.tick_running(5)
        self.assertEqual(self.store.pet()['hunger'], 65)

    def test_head_pat_daily_bonus_is_limited(self):
        for _ in range(10):
            self.assertTrue(self.store.interact(self.start))
        self.assertFalse(self.store.interact(self.start))
        self.assertEqual(self.store.pet()['mood'], 90)


if __name__ == '__main__':
    unittest.main()
