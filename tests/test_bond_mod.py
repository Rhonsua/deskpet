"""Offline growth and actual external-package lifecycle; never uses user data."""
import importlib.util
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from PySide6.QtWidgets import QApplication
from deskpet.mods import ModManager, ModManifest
from deskpet.mods.bond.store import BondStore, CATEGORIES, STAGES
from deskpet.mods.bond.mod import BondMod
from deskpet.mods.loader import discover
from deskpet.mods.services import InteractionServices
from deskpet.pet.store import PetStore


class BondFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'bond.db'
        self.store = BondStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.now = datetime(2026, 11, 16, 12)

    def test_five_categories_once_per_day_and_ten_minutes(self):
        for kind in ('headpat', 'feed', 'chat'):
            self.assertTrue(self.store.record(kind, {}, self.now))
            for _ in range(25):self.assertFalse(self.store.record(kind, {}, self.now))
        for invalid in (-1, 0, 6, float('nan'), float('inf')):
            self.assertFalse(self.store.record('listen', {'seconds':invalid}, self.now))
        for _ in range(119):
            self.assertFalse(self.store.record('listen', {'seconds':5,'title':'真实的歌'}, self.now))
        self.assertEqual(self.store.value['affinity'], 30)
        self.assertTrue(self.store.record('listen', {'seconds':5,'title':'真实的歌'}, self.now))
        self.assertTrue(self.store.game('真实的歌', 100, 1, self.now))
        self.assertFalse(self.store.game('真实的歌', 800, 8, self.now))
        self.assertEqual(self.store.daily(self.now), set(CATEGORIES))
        self.assertEqual(self.store.value['affinity'], 50)
        self.assertEqual(self.store.stage, 1)
        self.assertEqual(len([r for r in self.store.memories() if r['id']=='action:headpat']), 1)
        self.assertIn('stage:1', {r['id'] for r in self.store.memories()})
        self.assertNotIn('action:not-real', {r['id'] for r in self.store.memories()})
        self.assertFalse(self.store.record('action', {'action':'not-real'}, self.now))

    def test_midnight_rollback_absence_and_restart(self):
        self.store.award('chat', self.now)
        tomorrow = self.now + timedelta(days=1)
        self.assertTrue(self.store.award('chat', tomorrow))
        self.assertFalse(self.store.award('chat', self.now))
        self.store.close()
        self.store = BondStore(self.path)
        self.assertFalse(self.store.award('chat', self.now))
        self.assertEqual(self.store.value['affinity'], 20)
        self.assertEqual(self.store.daily(self.now+timedelta(days=100)), set())
        self.assertEqual(self.store.value['affinity'], 20)
        self.assertEqual(len([r for r in self.store.memories() if r['id']=='first-meeting']),1)

    def test_scroll_credits_old_daily_records_and_preserves_advanced_bookmarks(self):
        with self.store.db:
            self.store.db.executemany('INSERT INTO daily VALUES(?,?)', [
                ('2026-11-14', 'feed'), ('2026-11-14', 'chat'), ('2026-11-15', 'feed'),
                ('2026-11-15', 'unknown')])
        self.assertEqual(self.store.scroll_unlocked(), 4)
        self.store.configure('river_scroll_joined', 9)
        self.store.close()
        self.store = BondStore(self.path)
        self.assertEqual((self.store.scroll_joined(), self.store.scroll_unlocked()), (9, 9))
        self.assertFalse(self.store.join_scroll(10))
        self.assertTrue(self.store.record('headpat', {}, self.now))
        self.assertEqual(self.store.scroll_unlocked(), 10)
        self.assertTrue(self.store.join_scroll(10))
        self.assertFalse(self.store.join_scroll(10))
        self.store.close()
        self.store = BondStore(self.path)
        self.assertFalse(self.store.record('headpat', {}, self.now))
        self.assertEqual((self.store.scroll_joined(), self.store.scroll_unlocked()), (10, 10))

    def test_finished_scroll_memory_survives_a_missing_legacy_bookmark(self):
        with self.store.db:
            self.store.card('river-scroll-complete', '第一次拼好洛天依上河图', now=self.now)
        self.store.close()
        self.store = BondStore(self.path)
        self.assertEqual((self.store.scroll_joined(), self.store.scroll_unlocked()), (18, 18))
        self.store.award('game', self.now)
        self.assertFalse(self.store.join_scroll(19))
        self.assertEqual(self.store.scroll_unlocked(), 18)

    def test_highest_day_also_tracks_partial_listening(self):
        future = self.now + timedelta(days=2)
        self.store.record('listen', {'seconds':5}, future)
        self.store.record('listen', {'seconds':5}, self.now)
        self.assertEqual(self.store.listen_seconds(future), 10)
        self.assertEqual(self.store.day(self.now), future.date().isoformat())

    def test_six_stages_are_affinity_projections(self):
        for day in range(28):
            for kind in CATEGORIES:self.store.award(kind, self.now+timedelta(days=day))
        self.assertEqual(self.store.value['affinity'], 1400)
        self.assertEqual(self.store.projection()['level'], 6)
        self.assertEqual(self.store.projection()['xp'], self.store.projection()['xp_goal'])
        self.assertEqual(len([r for r in self.store.memories() if r['id'].startswith('stage:')]), 5)
        self.assertEqual(self.store.projection()['stage'], STAGES[-1][0])

    def test_weekly_facts_only_from_current_week(self):
        self.store.award('feed', self.now-timedelta(days=1))
        for _ in range(12):self.store.record('listen', {'seconds':5,'title':'已听歌曲'}, self.now)
        self.store.award('chat', self.now)
        text = self.store.weekly(self.now)
        self.assertIn('已听歌曲', text)
        self.assertIn('说说话：1 天', text)
        self.assertNotIn('投喂：', text)
        self.assertNotIn('完整', text)

    def test_chart_integrity_favorites_results_and_same_session_no_duplicate(self):
        from deskpet.mods.bond.chart import generate
        chart=generate({},seed=7);self.store.save_chart(chart,True)
        judge=SimpleNamespace(score=900000,best=30,perfect=30,good=0,misses=1,holds=2)
        self.assertTrue(self.store.complete_round('round-1',chart['id'],'练习',judge,now=self.now))
        self.assertFalse(self.store.complete_round('round-1',chart['id'],'练习',judge,now=self.now+timedelta(days=1)))
        self.assertEqual(self.store.value['affinity'],10);self.assertEqual(self.store.best(chart['id']),(900000,30))
        self.assertEqual(self.store.favorite_charts()[0][1],chart)
        chart['notes'][0]['lane']=(chart['notes'][0]['lane']+1)%3
        with self.assertRaises(ValueError):self.store.save_chart(chart)

    def test_memories_delete_and_completed_shows_are_idempotent(self):
        self.store.fact('favorite','真实偏好',self.now)
        key=self.store.recent_facts('favorite',7,self.now)[0]['id'];self.store.forget(key)
        self.assertEqual(self.store.recent_facts('favorite',7,self.now),[])
        self.assertTrue(self.store.completed_song('play-1','song','歌曲',self.now))
        self.assertFalse(self.store.completed_song('play-1','song','歌曲',self.now))
        program=[dict(title=str(i),path=str(i)) for i in range(3)]
        self.assertTrue(self.store.record_show('show',program,self.now))
        self.assertFalse(self.store.record_show('show',program,self.now))
        self.assertIn('共同完成三曲演出 1 次',self.store.weekly(self.now))

    def test_old_schema_backup_keeps_original_affinity(self):
        self.store.award('chat',self.now);self.store.db.execute('PRAGMA user_version=0');self.store.close()
        self.store=BondStore(self.path)
        import sqlite3
        old=sqlite3.connect(self.path.with_name('bond.previous.db'))
        try:self.assertEqual(old.execute('SELECT affinity FROM state').fetchone()[0],10)
        finally:old.close()
        self.assertEqual(self.store.value['affinity'],10)


class BondIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pet_store = PetStore(self.root/'pet.db')
        self.addCleanup(self.pet_store.close)
        from PySide6.QtCore import QSettings
        panel = SimpleNamespace(store=self.pet_store, settings=QSettings(str(self.root/'settings.ini'),QSettings.IniFormat),song_title=SimpleNamespace(text=lambda:'测试歌曲'),
            current_path=lambda:None, playback_source='local', volume=SimpleNamespace(value=lambda:50))
        self.pet = SimpleNamespace(panel=panel, character_name='洛天依', dragging=False, petting=False,
            playing=False, behavior=SimpleNamespace(layers=[],mode='idle',activity='idle'),
            scaled_frames={'happy':True,'sing-front':True}, react=Mock())
        self.host = SimpleNamespace(pet=self.pet)
        self.services = InteractionServices(self.host)
        self.manager = ModManager(self.root/'data', lambda _:True, services=self.services)
        self.host.manager = self.manager
        self.pet_store.event_listener = self.services.emit
        self.addCleanup(self.manager.shutdown)
        self.manager.register(ModManifest('bond','互动养成','0.1.0',api_version=2),BondMod)

    def enable(self):
        self.assertTrue(self.manager.set_enabled('bond',True),self.manager.error('bond'))
        return self.manager._running['bond']

    def test_old_progress_frozen_notes_preserved_and_disable_restores(self):
        with self.pet_store.db:
            self.pet_store.db.execute('UPDATE pet SET level=11,xp=33')
        mod = self.enable()
        self.assertEqual(self.pet_store.pet()['stage'],'初识')
        now = datetime.now()
        for i in range(120):self.pet_store.record('song.mp3',5,end=now+timedelta(seconds=5*i))
        self.assertEqual(self.pet_store.pet()['notes'],32)
        self.assertEqual(mod.store.value['affinity'],10)
        self.assertTrue(self.pet_store.feed('小包子',now)[0])
        self.assertEqual(mod.store.value['affinity'],20)
        self.assertFalse(self.pet_store.feed('小包子',now)[0])
        for _ in range(10):self.pet_store.emit('headpat')
        self.assertEqual(mod.store.value['affinity'],30)
        self.assertTrue(self.manager.set_enabled('bond',False))
        pet = self.pet_store.pet()
        self.assertEqual((pet['level'],pet['xp'],pet['notes']),(11,33,24))
        self.assertNotIn('stage',pet)
        self.assertEqual(self.services.memory_context(),'')
        self.assertEqual(self.services.listeners,{})
        mod = self.enable()
        self.assertEqual(mod.store.value['affinity'],30)

    def test_muted_listening_cannot_award_or_enter_memories(self):
        mod = self.enable()
        for _ in range(120):self.pet_store.record('song.mp3',5,reward=False)
        self.assertEqual(mod.store.value['affinity'],0)
        self.assertEqual(mod.store.listen_seconds(),0)

    def test_mode_switch_does_not_forge_an_old_level_up(self):
        from deskpet.app import MusicPanel
        panel=self.pet.panel
        panel.growth=Mock();panel.experience=Mock();panel.pet=self.pet
        with self.pet_store.db:self.pet_store.db.execute('UPDATE pet SET level=11,xp=33')
        MusicPanel.refresh_growth(panel)
        mod=self.enable()
        MusicPanel.refresh_growth(panel)
        for kind in ('headpat','feed','chat','game'):mod.store.award(kind)
        MusicPanel.refresh_growth(panel)
        self.manager.set_enabled('bond',False)
        MusicPanel.refresh_growth(panel)
        self.pet.react.assert_not_called()
        with self.pet_store.db:self.pet_store.db.execute('UPDATE pet SET level=12,xp=0')
        MusicPanel.refresh_growth(panel)
        self.pet.react.assert_called_once()

    def test_music_games_share_one_daily_wallet_reward(self):
        mod = self.enable()
        judge = SimpleNamespace(score=500000, best=5, perfect=5, good=0, misses=5, holds=0)
        mod.store.complete_round('rhythm-first', 'chart-a', '练习', judge)
        mod.store.complete_round('quiz-next', 'chart-b', '猜歌', judge, kind='quiz')
        mod.store.complete_round('quiz-next', 'chart-b', '猜歌', judge, kind='quiz')
        self.assertEqual(self.pet_store.stats()['daily_interactions'], {'game': 10})
        self.assertEqual(self.pet_store.pet()['notes'], 30)
        self.manager.set_enabled('bond', False)
        self.assertEqual(self.services.for_mod('bond').game_completed(), 0)

    def test_actual_combo_and_persona_facts(self):
        mod = self.enable()
        self.pet_store.emit('headpat');self.pet_store.feed('小包子')
        self.assertIn('combo:snack',{r['id'] for r in mod.store.memories()})
        mod.event('chat',{});mod.finish_game('练习',100,1)
        mod.store.nickname('朋友')
        self.assertIn('朋友',self.services.memory_context())
        self.assertNotIn('本地记录',self.services.memory_context())

    def test_competing_growth_and_failing_callback_release_only_owner(self):
        self.enable()
        self.manager.register(ModManifest('other','另一个','0.1.0',api_version=2),BondMod)
        self.assertFalse(self.manager.set_enabled('other',True))
        self.assertEqual(self.services.growth_owner,'bond')
        self.assertTrue(self.manager.is_enabled('bond'))
        self.services.subscribe('bond',Mock(side_effect=ValueError('bad callback')))
        self.pet_store.emit('headpat')
        self.assertFalse(self.manager.is_enabled('bond'))
        self.assertIsNone(self.pet_store.growth_provider)
        self.assertEqual(self.pet_store.pet()['level'],1)

    def test_invalid_projection_and_constructor_failure_restore_host(self):
        self.enable()
        self.services.growth('bond', lambda:{'level':1,'xp':-5,'xp_goal':40})
        self.assertEqual(self.pet_store.pet()['xp'],0)
        self.assertFalse(self.manager.is_enabled('bond'))
        def broken(context):
            context.services.growth(lambda:{'level':1,'xp':0,'xp_goal':40})
            raise ValueError('construction failed')
        self.manager.register(ModManifest('broken','错误包','0.1.0',api_version=2),broken)
        self.assertFalse(self.manager.set_enabled('broken',True))
        self.assertIsNone(self.pet_store.growth_provider)

    def test_snapshot_and_user_actions_have_priority(self):
        self.enable()
        analysis = {'beats_ms':[0,500,1000]}
        self.pet.music_companion=SimpleNamespace(beats=SimpleNamespace(source='local:a.mp3',analysis=analysis))
        self.assertEqual(self.services.snapshot()['beats'],{})
        self.assertEqual(self.services.snapshot(music=True)['beats'],analysis)
        self.assertIsNot(self.services.snapshot(music=True)['beats'],analysis)
        for field in ('dragging','petting','dock_edge'):
            setattr(self.pet,field,True)
            self.assertFalse(self.services.act('bond','happy'))
            setattr(self.pet,field,False)
        self.pet.work_preview_until=time.monotonic()+10
        self.assertFalse(self.services.act('bond','happy'))
        self.pet.work_preview_until=0
        self.pet.behavior.mode='sleep'
        self.assertFalse(self.services.act('bond','happy'))
        self.pet.behavior.mode='idle'
        self.assertTrue(self.services.act('bond','happy'))
        self.pet.react.assert_called_once_with('happy',seconds=2.,automatic=True)

    def test_shop_atomic_payment_duplicate_and_failure(self):
        self.enable()
        with self.pet_store.db:self.pet_store.db.execute('UPDATE pet SET notes=100')
        self.assertTrue(self.services.buy('bond','ocean')[0]);self.assertTrue(self.services.buy('bond','ocean')[0])
        self.assertEqual(self.pet_store.pet()['notes'],40);self.assertEqual(self.services.owned('bond'),['ocean'])
        self.assertFalse(self.services.buy('bond','sakura')[0]);self.assertFalse(self.services.buy('bond','missing')[0])
        with self.pet_store.db:
            self.pet_store.db.execute('UPDATE pet SET notes=200')
            self.pet_store.db.execute("CREATE TRIGGER stop_purchase BEFORE INSERT ON mod_purchases BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.DatabaseError):self.services.buy('bond','gold')
        self.assertEqual(self.pet_store.pet()['notes'],200);self.assertNotIn('gold',self.services.owned('bond'))

    def test_main_panel_direct_entry_and_lease_removed_on_disable(self):
        mod=self.enable();self.assertEqual(len(self.services.panel_items()),1)
        self.services.invoke('bond','rhythm');self.app.processEvents()
        self.assertEqual(mod.direct.widget.tabs.currentIndex(),1)
        mod.direct.widget.play();self.app.processEvents()
        from deskpet.mods.bond.rhythm import RhythmGame
        game=mod.games[-1];self.assertIsInstance(game,RhythmGame)
        self.assertFalse(game.requested)
        token=self.services.audio_claim('bond');self.assertTrue(token)
        self.assertIsNone(self.services.audio_claim('bond'))
        self.manager.set_enabled('bond',False);self.app.processEvents()
        self.assertEqual(self.services.panel_items(),[]);self.assertIsNone(self.services.audio_owner)

    def test_mixed_lease_coexists_with_regular_music_and_respects_other_activities(self):
        api=self.enable().services
        self.pet.playing=True
        self.assertIsNone(api.audio_claim())
        token=api.audio_claim_mixed();self.assertTrue(token)
        self.assertIsNone(api.audio_claim_mixed())
        self.pet.playing=False
        self.assertTrue(api.audio_valid(token));self.assertIsNone(api.audio_claim())
        self.pet.panel.settings.setValue('audio_output_id','test-device')
        self.assertEqual(api.audio_preferences(),(.5,'test-device'))
        self.manager.set_enabled('bond',False)
        self.assertFalse(api.audio_valid(token));self.assertIsNone(api.audio_claim_mixed())

    def test_need_quiet_real_response_and_daily_quota(self):
        mod=self.enable()
        for kind in ('headpat','feed','chat','game'):mod.store.award(kind)
        mod.context=SimpleNamespace(notify=Mock(return_value=True))
        with patch('deskpet.mods.bond.events.random.choice',return_value=('quiet','安静十五秒')):
            mod.events.tick();self.assertIsNotNone(mod.events.active)
        mod.events.event('feed',{});self.assertIsNone(mod.events.active)
        self.assertNotIn('need:quiet',{r['id'] for r in mod.store.memories()})
        mod.events.last_check=0
        with patch('deskpet.mods.bond.events.random.choice',return_value=('headpat','摸摸头')):mod.events.tick()
        self.pet.petting=True;mod.events.tick();self.assertIsNotNone(mod.events.active)
        mod.events.event('headpat',{});self.assertIn('need:headpat',{r['id'] for r in mod.store.memories()})
        mod.store.configure('needs_per_day',0);mod.events.last_check=0;self.pet.petting=False;mod.events.tick()
        self.assertIsNone(mod.events.active)

    def test_host_entrances_do_not_start_interaction_or_award(self):
        mod=self.enable()
        self.pet.open_tools=Mock();self.pet.open_chat=Mock();self.pet.chat_window=object()
        self.pet.toolbar=SimpleNamespace(page=Mock(),show=Mock(),raise_=Mock(),close_timer=SimpleNamespace(start=Mock()))
        self.pet.stop_roaming=Mock();self.pet.reveal_dock=Mock()
        with patch('deskpet.pet.desktop.clamp_near'):
            for destination in ('control','food','music','chat'):
                self.assertTrue(mod.services.present(destination))
        self.pet.toolbar.page.assert_any_call('home')
        self.pet.toolbar.page.assert_any_call('food')
        self.pet.open_tools.assert_called_once_with(0)
        self.pet.open_chat.assert_called_once_with()
        self.assertEqual(mod.store.value['affinity'],0)
        self.pet.react.assert_not_called()
        self.assertFalse(mod.services.present('unsupported'))
        self.manager.set_enabled('bond',False)
        self.assertFalse(self.services.present('bond','music'))

    def test_distribution_zip_loads_creates_ui_and_unloads(self):
        spec = importlib.util.spec_from_file_location('build_bond',Path(__file__).resolve().parents[1]/'packaging/build_bond_mod.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        output=builder.build(self.root/'bond.zip')
        packages=self.root/'packages'
        with zipfile.ZipFile(output) as archive:
            self.assertFalse(any(n.endswith('.db') for n in archive.namelist()))
            archive.extractall(packages)
        found,warnings=discover(packages)
        self.assertEqual(warnings,[])
        self.assertEqual(len(found),1)
        manifest,factory=found[0]
        isolated=ModManager(self.root/'external',lambda _:True,services=self.services)
        self.host.manager=isolated
        self.addCleanup(isolated.shutdown)
        isolated.register(manifest,factory)
        self.assertTrue(isolated.set_enabled('bond',True),isolated.error('bond'))
        widget=isolated.create_widget('bond')
        self.assertIsNotNone(widget,isolated.error('bond'))
        widget.show();self.app.processEvents()
        self.assertIn('初识',widget.heading.text())
        for kind in ('headpat','feed','chat'):self.pet_store.emit(kind)
        self.assertIn('30',widget.detail.text())
        self.assertTrue(isolated.set_enabled('bond',False))
        self.assertFalse(widget.isVisible())
        self.assertIsNone(self.pet_store.growth_provider)
        self.assertTrue(isolated.set_enabled('bond',True))
        self.assertEqual(self.pet_store.pet()['affinity'],30)
        widget.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
