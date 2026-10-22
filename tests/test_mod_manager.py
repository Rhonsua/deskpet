"""Isolated trusted-mod lifecycle and shared reminder ledger tests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pet_mods import ModContext, ModManager, ModManifest


class FakeMod:
    def __init__(self, context, fail=''):
        self.context = context
        self.fail = fail
        self.starts = 0
        self.stops = 0
        self.ticks = []

    def start(self):
        self.starts += 1
        if self.fail == 'start':
            raise RuntimeError('start test')

    def stop(self):
        self.stops += 1
        if self.fail == 'stop':
            raise RuntimeError('stop test')

    def tick(self, now):
        self.ticks.append(now)
        if self.fail == 'tick':
            raise RuntimeError('tick test')

    def create_widget(self, parent=None):
        if self.fail == 'widget':
            raise RuntimeError('widget test')
        return ('widget', parent)


class ModManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'mods'
        self.now = datetime(2026, 10, 21, 12)
        self.deliver = Mock(return_value=True)
        self.manager = ModManager(self.root, self.deliver, lambda: self.now)
        self.instances = {}
        self.addCleanup(self.manager.shutdown)

    def register(self, mod_id='goals', fail='', manager=None):
        manager = manager or self.manager
        def factory(context):
            mod = FakeMod(context, fail)
            self.instances[mod_id] = mod
            return mod
        manager.register(ModManifest(mod_id, '测试Mod', '1.0.0'), factory)

    def enable(self, mod_id='goals'):
        self.register(mod_id)
        self.assertTrue(self.manager.set_enabled(mod_id, True))
        return self.instances[mod_id]

    def test_default_closed_and_restore_enabled_with_data(self):
        self.register()
        self.assertFalse(self.manager.is_enabled('goals'))
        self.assertNotIn('goals', self.instances)
        self.assertIsNone(self.manager.create_widget('goals'))
        self.assertTrue(self.manager.set_enabled('goals', True))
        mod = self.instances['goals']
        self.assertIsInstance(mod.context, ModContext)
        archive = mod.context.data_dir / 'progress.json'
        archive.write_text('saved', encoding='utf-8')
        self.manager.tick()
        self.assertEqual(mod.ticks, [self.now])
        self.assertEqual(self.manager.create_widget('goals', 'parent'), ('widget', 'parent'))
        self.manager.shutdown()
        self.manager.shutdown()
        self.manager.tick()
        self.assertEqual(mod.stops, 1)
        self.assertEqual(len(mod.ticks), 1)
        restored = ModManager(self.root, self.deliver, lambda: self.now)
        self.addCleanup(restored.shutdown)
        self.register(manager=restored)
        self.assertTrue(restored.is_enabled('goals'))
        self.assertEqual(archive.read_text(), 'saved')
        self.assertTrue(restored.set_enabled('goals', False))
        self.assertTrue(restored.set_enabled('goals', False))
        self.assertEqual(self.instances['goals'].stops, 1)
        self.assertEqual(archive.read_text(), 'saved')
        self.assertFalse(restored.is_enabled('goals'))

    def test_disabled_manager_exit_creates_no_settings_or_mod_archive(self):
        self.register()
        self.manager.shutdown()
        self.manager.shutdown()
        self.assertFalse((self.root / 'settings.json').exists())
        self.assertFalse((self.root / 'goals').exists())

    def test_resolved_mod_directory_cannot_escape_root(self):
        self.register()
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            if path.name == 'goals':
                return self.root.parent / 'outside'
            return original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            self.assertFalse(self.manager.set_enabled('goals', True))
        self.assertNotIn('goals', self.instances)
        self.assertFalse((self.root.parent / 'outside').exists())
        self.assertTrue(self.manager.error('goals'))

    def test_reminder_budget_is_shared_between_mods(self):
        first = self.enable('first')
        second = self.enable('second')
        self.manager.set_policy(daily_limit=1)
        self.assertTrue(first.context.notify('第一个Mod'))
        self.now += timedelta(hours=3)
        self.assertFalse(second.context.notify('第二个Mod共享配额'))
        self.assertEqual(self.deliver.call_count, 1)

    def test_manifest_validation_duplicate_and_unknown_id(self):
        for manifest in [ModManifest('../escape', 'x', '1.0'), ModManifest('UPPER', 'x', '1.0'),
                         ModManifest('ok', '', '1.0'), ModManifest('ok', 'x', ''),
                         ModManifest('ok', 'x', 'not-version'), ModManifest('ok', 'x', '1.0', api_version=True),
                         ModManifest('ok', 'x', '1.0', api_version=2)]:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                self.manager.register(manifest, FakeMod)
        self.register()
        with self.assertRaises(ValueError):
            self.register()
        self.assertFalse(self.manager.set_enabled('unknown', True))
        self.assertFalse(self.manager.set_enabled('goals', 1))
        self.assertEqual([m.id for m in self.manager.manifests()], ['goals'])

    def test_start_tick_widget_and_stop_faults_are_isolated(self):
        healthy = self.enable('healthy')
        for phase in ['start', 'tick', 'widget', 'stop']:
            mod_id = 'bad_' + phase
            self.register(mod_id, phase)
            enabled = self.manager.set_enabled(mod_id, True)
            if phase == 'start':
                self.assertFalse(enabled)
            elif phase == 'tick':
                self.manager.tick()
            elif phase == 'widget':
                self.assertIsNone(self.manager.create_widget(mod_id))
            else:
                self.assertFalse(self.manager.set_enabled(mod_id, False))
            self.assertFalse(self.manager.is_enabled(mod_id))
            self.assertTrue(self.manager.error(mod_id))
            self.assertEqual(self.instances[mod_id].stops, 1)
        self.assertTrue(self.manager.is_enabled('healthy'))
        self.manager.tick()
        self.assertTrue(healthy.ticks)

    def test_invalid_settings_fall_back_closed(self):
        cases = [b'{broken', b'[]', b'{}', b'\xff', b' ' * 65537,
                 b'{"version":1,"version":1}',
                 json.dumps(dict(version=True, enabled=[], policy={}, reminders={})).encode()]
        for index, content in enumerate(cases):
            directory = self.root / str(index)
            directory.mkdir()
            (directory / 'settings.json').write_bytes(content)
            manager = ModManager(directory, self.deliver, lambda: self.now)
            self.addCleanup(manager.shutdown)
            self.register('test', manager=manager)
            self.assertFalse(manager.is_enabled('test'))
            self.assertTrue(manager.warning)
            self.assertEqual(manager.get_policy()['daily_limit'], 3)

    def test_policy_strict_validation_and_copy(self):
        before = self.manager.get_policy()
        before['daily_limit'] = 20
        self.assertEqual(self.manager.get_policy()['daily_limit'], 3)
        for values in [dict(sound_enabled=1), dict(sound_enabled='false'), dict(sound_enabled=None),
                       dict(quiet_enabled=1), dict(quiet_start=True), dict(quiet_start=24),
                       dict(quiet_end=-1), dict(daily_limit=0), dict(daily_limit=21),
                       dict(daily_limit=1.0), dict(min_interval_minutes=0),
                       dict(min_interval_minutes=1441), dict(unknown=True)]:
            with self.subTest(values=values):
                self.assertFalse(self.manager.set_policy(**values))
        self.assertTrue(self.manager.set_policy(daily_limit=20, min_interval_minutes=1, quiet_start=0, quiet_end=23))

    def test_sound_default_and_disabled_setting_persist(self):
        self.assertIs(self.manager.get_policy()['sound_enabled'], True)
        self.assertTrue(self.manager.set_policy(sound_enabled=False))
        restored = ModManager(self.root, self.deliver, lambda: self.now)
        self.addCleanup(restored.shutdown)
        self.assertIs(restored.get_policy()['sound_enabled'], False)
        self.assertFalse(restored.warning)

    def test_legacy_schema_one_policy_gets_sound_default(self):
        self.assertTrue(self.manager.set_policy(daily_limit=5))
        path = self.root / 'settings.json'
        settings = json.loads(path.read_text(encoding='utf-8'))
        del settings['policy']['sound_enabled']
        path.write_text(json.dumps(settings), encoding='utf-8')
        restored = ModManager(self.root, self.deliver, lambda: self.now)
        self.addCleanup(restored.shutdown)
        self.assertFalse(restored.warning)
        self.assertIs(restored.get_policy()['sound_enabled'], True)
        self.assertEqual(restored.get_policy()['daily_limit'], 5)
        self.assertTrue(restored.set_policy(min_interval_minutes=60))
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertIs(saved['policy']['sound_enabled'], True)

    def test_overnight_and_all_day_quiet_hours(self):
        mod = self.enable()
        for now in [datetime(2026, 10, 21, 22), datetime(2026, 10, 21, 23, 59),
                    datetime(2026, 10, 22, 0), datetime(2026, 10, 22, 7, 59)]:
            self.now = now
            self.assertFalse(mod.context.notify('提醒'))
        self.deliver.assert_not_called()
        self.now = datetime(2026, 10, 22, 8)
        self.assertTrue(mod.context.notify('提醒'))
        self.assertTrue(self.manager.set_policy(quiet_start=8, quiet_end=8))
        self.now += timedelta(hours=3)
        self.assertFalse(mod.context.notify('全天免扰'))
        self.assertTrue(self.manager.set_policy(quiet_enabled=False))
        self.assertTrue(mod.context.notify('允许'))

    def test_daytime_quiet_period(self):
        mod = self.enable()
        self.assertTrue(self.manager.set_policy(quiet_start=10, quiet_end=14))
        self.assertFalse(mod.context.notify('中午免扰'))
        self.now = self.now.replace(hour=14)
        self.assertTrue(mod.context.notify('下午允许'))

    def test_daily_budget_and_interval_persist_across_midnight_restart(self):
        mod = self.enable()
        self.assertTrue(self.manager.set_policy(quiet_enabled=False, daily_limit=1, min_interval_minutes=120))
        self.now = datetime(2026, 10, 21, 23, 50)
        self.assertTrue(mod.context.notify('第一天'))
        self.assertFalse(mod.context.notify('同日超额'))
        self.manager.shutdown()
        restored = ModManager(self.root, self.deliver, lambda: self.now)
        self.addCleanup(restored.shutdown)
        self.register(manager=restored)
        mod = self.instances['goals']
        self.now = datetime(2026, 10, 22, 0, 10)
        self.assertFalse(mod.context.notify('跨天但间隔不足'))
        self.now = datetime(2026, 10, 22, 1, 50)
        self.assertTrue(mod.context.notify('第二天'))
        self.now = datetime(2026, 10, 22, 4)
        self.assertFalse(mod.context.notify('第二天超额'))
        self.assertEqual(self.deliver.call_count, 2)

    def test_host_rejection_and_exception_do_not_consume_budget(self):
        mod = self.enable()
        self.manager.set_policy(daily_limit=1)
        self.deliver.return_value = False
        self.assertFalse(mod.context.notify('被宿主阻止'))
        self.deliver.side_effect = RuntimeError('host failure')
        self.assertFalse(mod.context.notify('宿主异常'))
        self.deliver.side_effect = None
        self.deliver.return_value = True
        self.assertTrue(mod.context.notify('仍可提醒'))
        self.assertEqual(self.manager._reminders['count'], 1)

    def test_clock_rollback_keeps_interval_and_budget(self):
        mod = self.enable()
        self.assertTrue(mod.context.notify('已送出'))
        self.now -= timedelta(days=1)
        self.assertFalse(mod.context.notify('回拨一天'))
        self.now = datetime(2026, 10, 21, 11, 59)
        self.assertFalse(mod.context.notify('回拨一分钟'))
        self.now = datetime(2026, 10, 21, 14)
        self.assertTrue(mod.context.notify('恢复时间'))

    def test_storage_failure_rolls_back_settings_and_blocks_reminders(self):
        self.register()
        with patch('pet_mods.manager.os.replace', side_effect=OSError('isolated test')):
            self.assertFalse(self.manager.set_enabled('goals', True))
            self.assertFalse(self.manager.is_enabled('goals'))
            self.assertFalse(self.manager.set_policy(daily_limit=20))
        self.assertEqual(self.manager.get_policy()['daily_limit'], 3)
        self.assertTrue(self.manager.warning)
        self.assertTrue(self.manager.set_enabled('goals', True))
        mod = self.instances['goals']
        with patch('pet_mods.manager.os.replace', side_effect=OSError('isolated test')):
            self.assertFalse(mod.context.notify('不能记账就不提醒'))
        self.assertFalse(mod.context.notify('本次会话继续关闭提醒'))
        self.deliver.assert_not_called()
        self.assertEqual(list(self.root.glob('settings-*.tmp')), [])

    def test_host_rejection_rollback_failure_blocks_future_delivery(self):
        mod = self.enable()
        self.deliver.return_value = False
        original = self.manager._save
        calls = []
        def save():
            calls.append(True)
            return original() if len(calls) == 1 else False
        with patch.object(self.manager, '_save', save):
            self.assertFalse(mod.context.notify('阻止且回滚失败'))
        self.deliver.return_value = True
        self.assertFalse(mod.context.notify('保持关闭'))
        self.assertEqual(self.deliver.call_count, 1)

    def test_invalid_text_disabled_and_aware_clock_never_deliver(self):
        mod = self.enable()
        for text in ['', ' ', 'x' * 501, '<b>html</b>', '\x00hello', 12]:
            self.assertFalse(mod.context.notify(text))
        self.now = self.now.replace(tzinfo=timezone.utc)
        self.assertFalse(mod.context.notify('错误时间类型'))
        self.manager.tick()
        self.assertEqual(mod.ticks, [])
        self.manager.set_enabled('goals', False)
        self.assertFalse(mod.context.notify('停用'))
        self.deliver.assert_not_called()


if __name__ == '__main__':
    unittest.main()
