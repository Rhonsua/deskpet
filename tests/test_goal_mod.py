"""Deterministic goal reminders and persistence, using only disposable databases."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pet_mods.goals.store import GoalStore
from pet_mods.goals.mod import GoalMod


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='pet-goals-')
        self.root = Path(self.directory.name)
        self.sent = []
        self.accept = True
        self.now = datetime(2026, 10, 21, 23, 30)
        self.context = SimpleNamespace(data_dir=self.root, notify=self.notify)
        self.mod = GoalMod(self.context)
        self.mod.start()
        self.store = self.mod.store

    def notify(self, text):
        self.sent.append(text)
        return self.accept

    def tearDown(self):
        self.mod.stop()
        self.directory.cleanup()

    def create(self, title='写完一首歌', deadline=None, steps=(), days=2):
        return self.store.create(title, deadline or self.now + timedelta(days=10),
                                 steps, days, now=self.now)

    def test_lazy_lifecycle_and_restart(self):
        other = GoalMod(SimpleNamespace(data_dir=self.root / 'off', notify=self.notify))
        other.tick(self.now)
        self.assertFalse((self.root / 'off').exists())
        other.stop()
        goal_id = self.create(steps=['写主歌'])
        self.store.set_step_done(goal_id, 0, True, self.now + timedelta(hours=1))
        self.mod.stop()
        self.mod.stop()
        self.mod.start()
        self.mod.start()
        goal = self.mod.store.get(goal_id)
        self.assertEqual(goal['steps'], [dict(text='写主歌', done=True)])
        self.assertEqual(goal['last_progress'], self.now + timedelta(hours=1))

    def test_no_fictional_progress_on_create_or_metadata_edit(self):
        goal_id = self.create(steps=['写主歌'])
        self.assertIsNone(self.store.get(goal_id)['last_progress'])
        self.store.update(goal_id, '改名', self.now + timedelta(days=8), ['写主歌'], 3,
                          now=self.now + timedelta(days=1), notes='写了一个备注')
        self.assertIsNone(self.store.get(goal_id)['last_progress'])
        self.assertEqual(self.store.get(goal_id)['notes'], '写了一个备注')

    def test_step_edit_retains_only_unchanged_occurrences(self):
        goal_id = self.create(steps=['重复', '重复', '保留', '修改'])
        self.store.set_step_done(goal_id, 0, True, self.now)
        self.store.set_step_done(goal_id, 2, True, self.now)
        self.store.set_step_done(goal_id, 3, True, self.now)
        self.store.update(goal_id, '新标题', self.now + timedelta(days=20),
                          ['保留', '重复', '新待办', '重复', '修改过'], now=self.now + timedelta(days=1))
        self.assertEqual([step['done'] for step in self.store.get(goal_id)['steps']],
                         [True, True, False, False, False])
        self.assertEqual(self.store.get(goal_id)['last_progress'], self.now)

    def test_manual_progress_does_not_check_steps(self):
        goal_id = self.create(steps=['第一步', '第二步'])
        later = self.now + timedelta(hours=4)
        self.store.record_progress(goal_id, later)
        goal = self.store.get(goal_id)
        self.assertEqual(goal['last_progress'], later)
        self.assertFalse(any(step['done'] for step in goal['steps']))
        self.store.set_step_done(goal_id, 0, False, later + timedelta(hours=1))
        self.assertEqual(self.store.get(goal_id)['last_progress'], later)

    def test_stagnation_exact_boundary_crosses_midnight(self):
        goal_id = self.create()
        self.mod.tick(self.now + timedelta(days=2) - timedelta(microseconds=1))
        self.assertEqual(self.sent, [])
        boundary = self.now + timedelta(days=2)
        self.mod.tick(boundary)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('未记录新进展', self.sent[0])
        self.assertNotIn('没有努力了', self.sent[0])
        self.assertEqual(self.store.get(goal_id)['last_reminded'], boundary)

    def test_due_in_24_hours_and_overdue_priority(self):
        self.create('临期', self.now + timedelta(hours=24))
        overdue = self.create('逾期', self.now - timedelta(minutes=1))
        self.create('停滞', self.now + timedelta(days=20), days=1)
        self.mod.tick(self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('逾期', self.sent[0])
        self.assertIn('截止时间', self.sent[0])
        self.assertEqual(self.store.get(overdue)['last_reminded'], self.now)
        self.mod.tick(self.now)
        self.assertEqual(len(self.sent), 2)
        self.assertIn('临期', self.sent[-1])

    def test_outside_24_hours_does_not_remind(self):
        self.create(deadline=self.now + timedelta(hours=24, microseconds=1))
        self.mod.tick(self.now)
        self.assertEqual(self.sent, [])

    def test_exact_deadline_is_due(self):
        self.create(deadline=self.now)
        self.mod.tick(self.now)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('截止时间', self.sent[0])

    def test_pause_resume_resets_stagnation_without_progress(self):
        goal_id = self.create(deadline=self.now + timedelta(days=30))
        self.store.set_status(goal_id, 'paused', self.now)
        self.mod.tick(self.now + timedelta(days=5))
        self.assertEqual(self.sent, [])
        resumed = self.now + timedelta(days=5)
        self.store.set_status(goal_id, 'active', resumed)
        self.assertIsNone(self.store.get(goal_id)['last_progress'])
        self.mod.tick(resumed + timedelta(days=2) - timedelta(seconds=1))
        self.assertEqual(self.sent, [])
        self.mod.tick(resumed + timedelta(days=2))
        self.assertEqual(len(self.sent), 1)

    def test_completed_and_paused_goals_never_notify(self):
        for status in ('completed', 'paused'):
            goal_id = self.create(status, self.now - timedelta(days=3))
            self.store.set_status(goal_id, status, self.now)
        self.mod.tick(self.now + timedelta(days=10))
        self.assertEqual(self.sent, [])

    def test_reopen_does_not_fake_progress_or_reset_cooldown(self):
        goal_id = self.create(deadline=self.now)
        self.mod.tick(self.now)
        self.store.set_status(goal_id, 'completed', self.now)
        self.store.set_status(goal_id, 'active', self.now + timedelta(hours=1))
        self.mod.tick(self.now + timedelta(hours=1))
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(self.store.get(goal_id)['last_progress'])

    def test_snooze_default_hour_and_restart(self):
        goal_id = self.create(deadline=self.now)
        self.store.snooze(goal_id, self.now)
        self.mod.stop()
        self.mod.start()
        self.mod.tick(self.now + timedelta(minutes=59))
        self.assertEqual(self.sent, [])
        self.mod.tick(self.now + timedelta(hours=1))
        self.assertEqual(len(self.sent), 1)

    def test_cooldown_24_hours_survives_restart(self):
        goal_id = self.create(deadline=self.now)
        self.mod.tick(self.now)
        self.mod.stop()
        self.mod.start()
        self.mod.tick(self.now + timedelta(hours=24) - timedelta(microseconds=1))
        self.assertEqual(len(self.sent), 1)
        self.mod.tick(self.now + timedelta(hours=24))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.mod.store.get(goal_id)['last_reminded'], self.now + timedelta(hours=24))

    def test_notify_rejected_does_not_start_cooldown(self):
        goal_id = self.create(deadline=self.now)
        self.accept = False
        self.mod.tick(self.now)
        self.assertIsNone(self.store.get(goal_id)['last_reminded'])
        self.accept = True
        self.mod.tick(self.now + timedelta(minutes=1))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.store.get(goal_id)['last_reminded'], self.now + timedelta(minutes=1))

    def test_database_failure_after_notify_does_not_spam(self):
        self.create(deadline=self.now)
        with patch.object(self.store, 'mark_reminded', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.Error):
                self.mod.tick(self.now)
        self.assertTrue(self.mod.last_error)
        self.mod.tick(self.now + timedelta(minutes=1))
        self.assertEqual(len(self.sent), 1)

    def test_tick_read_error_is_contained(self):
        with patch.object(self.store, 'list_goals', side_effect=sqlite3.OperationalError('locked')):
            with self.assertRaises(sqlite3.Error):
                self.mod.tick(self.now)
        self.assertTrue(self.mod.last_error)
        self.assertFalse(self.sent)

    def test_step_transaction_rolls_back_on_write_failure(self):
        goal_id = self.create(steps=['原步骤'])
        self.store.db.execute('''CREATE TRIGGER refuse_step BEFORE INSERT ON steps
            BEGIN SELECT RAISE(ABORT, 'test write failure'); END''')
        with self.assertRaises(sqlite3.Error):
            self.store.update(goal_id, '不应落盘的新名称', self.now, ['新步骤'])
        goal = self.store.get(goal_id)
        self.assertEqual(goal['title'], '写完一首歌')
        self.assertEqual(goal['steps'], [dict(text='原步骤', done=False)])

    def test_input_limits_and_sql_parameterization(self):
        invalid = [('', [], 2), ('a' * 121, [], 2), ('有效', ['x'] * 51, 2),
                   ('有效', ['x' * 201], 2), ('有效', [' '], 2), ('有效', [], 0),
                   ('有效', [], 31), ('有效', [], True)]
        for title, steps, days in invalid:
            with self.subTest(title=title[:8], days=days), self.assertRaises(ValueError):
                self.store.create(title, self.now, steps, days, self.now)
        with self.assertRaises(ValueError):
            self.store.create('有效', self.now.replace(tzinfo=timezone.utc), now=self.now)
        with self.assertRaises(ValueError):
            self.store.create('有效', self.now, notes='x' * 4001)
        title = "Robert'); DROP TABLE goals;--"
        goal_id = self.create(title)
        self.assertEqual(self.store.get(goal_id)['title'], title)

    def test_delete_cascades_and_user_goals_share_across_characters(self):
        goal_id = self.create(steps=['属于用户的步骤'])
        # Character switching is intentionally not an argument to this storage API.
        second = GoalStore(self.root / 'goals.db')
        try:
            self.assertEqual(second.get(goal_id)['steps'][0]['text'], '属于用户的步骤')
        finally:
            second.close()
        self.store.delete(goal_id)
        self.assertEqual(self.store.list_goals(), [])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM steps').fetchone()[0], 0)

    def test_deleted_goal_cooldown_not_inherited_by_new_goal(self):
        goal_id = self.create(deadline=self.now)
        self.mod.tick(self.now)
        self.store.delete(goal_id)
        new_id = self.create('新的目标', deadline=self.now)
        self.assertNotEqual(goal_id, new_id)
        self.mod.tick(self.now)
        self.assertEqual(len(self.sent), 2)
        self.assertIn('新的目标', self.sent[-1])


if __name__ == '__main__':
    unittest.main()
