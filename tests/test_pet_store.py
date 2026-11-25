import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from deskpet.pet.store import PetStore


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
        self.assertEqual((self.store.pet()['notes'], self.store.pet()['xp']), (26, 15))
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
        self.assertEqual(stats['reward_notes'], 6)
        self.assertEqual(stats['reward_limit'], 100)
        self.assertEqual(stats['reward_remaining'], 180)
        self.assertEqual(self.store.pet()['notes'], 18)
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
        self.assertEqual(self.store.pet()['notes'], 126)
        self.assertEqual(self.store.stats(tomorrow)['reward_notes'], 6)
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 100)

    def test_existing_old_cap_can_keep_earning_after_update(self):
        # Recreate the old daily-table layout and a partially earned block.
        self.store.db.executescript("""
            DROP TABLE daily;
            CREATE TABLE daily(day TEXT PRIMARY KEY, seconds REAL DEFAULT 0,
                blocks INTEGER DEFAULT 0,bonus INTEGER DEFAULT 0,feeds INTEGER DEFAULT 0);
            INSERT INTO daily VALUES('2026-10-17',7495,24,1,0);
            UPDATE pet SET notes=68,progress=295;
        """)
        self.store.close()
        self.store = PetStore(self.path)
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 48)
        self.assertEqual(self.store.stats(self.start)['reward_remaining'], 5)
        self.listen(5, start=self.start + timedelta(seconds=7495))
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 50)
        self.assertEqual(self.store.pet()['notes'], 70)

    def test_restart_retains_partial_reward(self):
        self.listen(295)
        self.store.close()
        self.store = PetStore(self.path)
        self.store.record('song.mp3', 5, True, self.start + timedelta(seconds=300))
        self.assertEqual(self.store.pet()['notes'], 26)
        self.assertEqual(self.store.pet()['progress'], 0)

    def test_midnight_split(self):
        self.store.record('song.mp3', 4, True, datetime(2026, 10, 18, 0, 0, 2))
        rows = self.store.db.execute('SELECT day,seconds FROM daily ORDER BY day').fetchall()
        self.assertEqual([(r['day'], r['seconds']) for r in rows],
                         [('2026-10-17', 2), ('2026-10-18', 2)])
        self.assertEqual(self.store.stats(datetime(2026, 10, 18))['reward_remaining'], 298)

    def test_first_hour_then_standard_rate(self):
        self.listen(3599)
        stats = self.store.stats(self.start)
        self.assertEqual((stats['reward_notes'], stats['next_reward_notes'], stats['reward_remaining']), (66, 6, 1))
        self.listen(1, start=self.start + timedelta(seconds=3599))
        stats = self.store.stats(self.start)
        self.assertEqual((stats['reward_notes'], stats['next_reward_notes']), (72, 2))
        self.listen(300, start=self.start + timedelta(seconds=3600))
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 74)
        self.listen(13 * 300, start=self.start + timedelta(seconds=3900))
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 100)
        self.assertIsNone(self.store.stats(self.start)['reward_remaining'])

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

    def test_daily_interaction_notes_restart_and_independent_listening_cap(self):
        self.listen(130 * 60)
        for kind, amount in (('headpat', 6), ('chat', 6), ('game', 10)):
            self.assertEqual(self.store.award_daily_notes(kind, self.start), amount)
        self.store.close()
        self.store = PetStore(self.path)
        for kind in ('headpat', 'chat', 'game'):
            self.assertEqual(self.store.award_daily_notes(kind, self.start), 0)
        self.assertEqual(self.store.stats(self.start)['reward_notes'], 100)
        self.assertEqual(self.store.stats(self.start)['companion_notes'], 22)
        tomorrow = self.start + timedelta(days=1)
        self.assertEqual(self.store.award_daily_notes('chat', tomorrow), 6)
        self.assertEqual(self.store.stats(tomorrow)['daily_interactions'], {'chat': 6})

    def test_company_notes_split_midnight_resume_and_stop_at_thirty_minutes(self):
        midnight = datetime(2026, 10, 18)
        for n in range(119):
            self.store.tick_running(5, midnight - timedelta(seconds=601 - 5*n))
        self.store.tick_running(3, midnight - timedelta(seconds=3))
        self.store.tick_running(4, midnight + timedelta(seconds=2))
        self.assertEqual(self.store.stats(midnight - timedelta(seconds=1))['daily_interactions'], {'company': 4})
        self.assertEqual(self.store.stats(midnight)['companion_seconds'], 2)
        self.store.tick_running(3600, midnight + timedelta(hours=1))
        self.store.close()
        self.store = PetStore(self.path)
        for n in range(370):
            self.store.tick_running(5, midnight + timedelta(seconds=7 + 5*n))
        stats = self.store.stats(midnight)
        self.assertEqual((stats['companion_seconds'], stats['companion_notes'], stats['reward_notes']), (1800, 12, 0))
        self.assertEqual(self.store.pet()['notes'], 36)

    def test_concurrent_daily_claims_share_one_wallet_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        both = Barrier(2)
        def claim():
            wallet = PetStore(self.path)
            try:
                both.wait(timeout=5)
                return wallet.award_daily_notes('chat', self.start)
            finally:
                wallet.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            self.assertEqual(sorted(f.result() for f in futures), [0, 6])
        self.assertEqual(self.store.pet()['notes'], 26)

    def test_auto_meal_crosses_strict_threshold_and_never_counts_as_manual_feed(self):
        events = []
        self.store.event_listener = lambda kind, data: events.append(kind)
        with self.store.db:
            self.store.db.execute('UPDATE pet SET hunger=10, runtime=1798, notes=8')
        self.assertIsNone(self.store.tick_running(1, self.start))
        self.assertEqual(self.store.pet()['hunger'], 10)
        self.assertEqual(self.store.tick_running(1, self.start).key, 'bao')
        self.assertEqual((self.store.pet()['notes'], self.store.pet()['hunger'], self.store.pet()['xp']), (0, 20, 0))
        self.assertEqual(events, [])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM daily').fetchone()[0], 0)
        self.store.close()
        self.store = PetStore(self.path)
        self.assertIsNone(self.store.tick_running(1, self.start))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM ledger').fetchone()[0], 1)

    def test_auto_meal_waits_for_notes_and_respects_switch(self):
        with self.store.db:
            self.store.db.execute('UPDATE pet SET hunger=0,notes=7')
        self.assertIsNone(self.store.tick_running(1))
        self.store.set_auto_meal(False)
        with self.store.db:
            self.store.db.execute('UPDATE pet SET notes=8')
        self.assertIsNone(self.store.tick_running(1))
        self.store.set_auto_meal(True)
        self.assertEqual(self.store.tick_running(1).name, '小包子')
        self.assertEqual((self.store.pet()['notes'], self.store.pet()['hunger']), (0, 15))

    def test_shop_gifts_and_permanent_items_share_wallet(self):
        self.assertFalse(self.store.buy_item('encore')[0])
        self.assertEqual(self.store.shop_settings()['background'], 'picnic')
        self.assertTrue(self.store.buy_item('pinwheel')[0])
        self.assertEqual((self.store.pet()['notes'], self.store.pet()['mood']), (14, 76))
        with self.store.db:
            self.store.db.execute('UPDATE pet SET notes=200')
        for key in ('bow', 'cloudsky', 'cloudsky'):
            self.assertTrue(self.store.buy_item(key)[0])
        self.assertEqual(self.store.pet()['notes'], 50)
        self.assertTrue(self.store.buy_item('cloudsky', remove=True)[0])
        self.assertEqual(self.store.shop_settings()['background'], '')
        self.store.close()
        self.store = PetStore(self.path)
        self.assertEqual(self.store.shop_settings()['accessory'], 'bow')
        self.assertIn('cloudsky', self.store.shop_owned())
        self.assertTrue(self.store.buy_item('cloudsky')[0])
        self.assertEqual(self.store.pet()['notes'], 50)


if __name__ == '__main__':
    unittest.main()
