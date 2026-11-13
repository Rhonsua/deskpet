import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QWidget
from tests.test_companion_music import MusicTests
from deskpet.chat.music_actions import chosen_item


class ChoiceTests(unittest.TestCase):
    setUp=MusicTests.setUp
    tearDown=MusicTests.tearDown
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    @contextmanager
    def window(self):
        from deskpet.chat.window import ChatWindow
        from deskpet.chat.config import ProviderConfig
        from deskpet.pet.behavior import PetBehavior
        pet=QWidget();pet.panel=self.p;self.p.pet=pet
        self.p.data_dir=Path(self.temp.name);self.p.settings=self.owner.settings
        self.p.store=NS(pet=lambda:{'level':1})
        pet.music_companion=None;pet.character_pack=None;pet.variant='refined';pet.character_name='洛天依'
        pet.behavior=PetBehavior();pet.dragging=pet.petting=pet.playing=False;pet.press_point=None
        pet.live2d_renderer=None;pet.scaled_frames={};pet.walk_supported=lambda:False
        pet.react=Mock();pet.bubble=NS(say=Mock());pet.show()
        with patch('deskpet.chat.companion_runtime.CompanionRuntime'):
            w=ChatWindow(pet)
            w.config=ProviderConfig(base_url='http://localhost:12345/v1',model='test')
            with patch.object(w,'request_client') as remote:
                try:yield w,remote
                finally:w.shutdown();pet.close()

    def test_music_mentions_are_conversation_until_api_requests_an_action(self):
        phrases = ('唱歌累不累', '唱歌是不是很开心', '你喜欢唱歌吗',
                   '唱《普通DISCO》的时候累吗', '播放音乐会打扰你吗',
                   '走路累不累', '睡觉舒服吗', '唱一下是什么意思',
                   '昨天我播放流光', '不要播放流光', '如果播放流光会怎样',
                   '他说“播放流光”', '播放《普通DISCO》这件事先别做')
        with self.window() as (w, remote), patch('deskpet.chat.music_actions.search') as search, patch(
                'deskpet.chat.actions.perform_action') as perform:
            # Previous successful commands must not authorize the next chat turn.
            w.store.add_turn(w.character, '唱一下普通DISCO', '这就播放。')
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    w.input.setPlainText(phrase)
                    self.assertTrue(w.send_message())
                    messages = remote.return_value.start.call_args.args[1]
                    self.assertEqual(messages[-1]['content'], phrase)
                    self.assertIsNone(w.music_choice)
                    self.assertIn('先理解整句话是在聊天还是要求现在执行', messages[0]['content'])
                    w.on_completed('[温柔]有你陪着，感觉很开心呀。')
                    self.assertIsNone(w.pending)
                    self.assertEqual(w.store.history(w.character)[-1]['content'], '有你陪着，感觉很开心呀。')
            self.assertEqual(remote.return_value.start.call_count, len(phrases))
            search.assert_not_called()
            perform.assert_not_called()
            self.p.start_track.assert_not_called()
            self.p.bilibili.start_process.assert_not_called()

    def test_api_confirmed_requests_search_real_tracks_before_claiming_success(self):
        with self.window() as (w,remote):
            w.input.setPlainText('播放本地普通DISCO');w.send_message()
            self.assertEqual(remote.return_value.start.call_count, 1)
            self.p.start_track.assert_not_called()
            w.on_completed('[动作:music_local {"pattern":"普通DISCO"}]好呀。')
            self.p.start_track.assert_called_once_with(2)
            self.assertIn('普通DISCO',w.store.history(w.character)[-1]['content'])
            w.input.setPlainText('播放不存在的歌');w.send_message()
            w.on_completed('[动作:music_play {"pattern":"不存在的歌"}]好呀。')
            self.assertEqual(remote.return_value.start.call_count, 2)
            self.assertIn('没找到',w.store.history(w.character)[-1]['content'])
            self.p.start_track.assert_called_once_with(2)

    def test_ambiguous_choice_has_no_paths_and_executes_once(self):
        with self.window() as (w,remote):
            w.input.setPlainText('播放流光');w.send_message()
            self.assertIsNone(w.music_choice)
            w.on_completed('[动作:music_play {"pattern":"流光"}]这就找。')
            messages=remote.return_value.start.call_args.args[1]
            serialized=json.dumps(messages,ensure_ascii=False)
            self.assertNotIn(self.temp.name,serialized);self.assertNotIn('https://',serialized)
            self.assertEqual(len(w.music_choice),3)
            target=next(str(i) for i,m in enumerate(w.music_choice) if m['source']=='local' and m['title']=='流光现场')
            self.assertEqual(w.store.history(w.character),[])
            w.on_partial('{"id":');self.assertEqual(w.partial_text,'')
            w.on_completed(json.dumps({'id':target}))
            self.p.start_track.assert_called_once_with(1)
            w.on_completed(json.dumps({'id':target}))
            self.assertEqual(self.p.start_track.call_count,1)
            self.assertNotIn('"id"',w.store.history(w.character)[-1]['content'])

    def test_invalid_id_cancellation_and_changed_playlist_prevent_playback(self):
        with self.window() as (w,_):
            for event in ('invalid','cancel','changed'):
                w.input.setPlainText('播放流光');w.send_message()
                w.on_completed('[动作:music_play {"pattern":"流光"}]这就找。')
                if event=='invalid':w.on_completed('{"id":"../../etc/passwd"}')
                elif event=='cancel':w.stop();w.on_completed('{"id":"0"}')
                else:
                    self.p.library.active['paths'].reverse();w.on_completed('{"id":"0"}')
                self.assertIsNone(w.pending)
            self.p.start_track.assert_not_called();self.p.bilibili.start_process.assert_not_called()

    def test_only_explicit_candidate_ids_are_admitted(self):
        rows=[{'title':'正常歌名','source':'local','key':'C:/private/song.mp3'}]
        self.assertEqual(chosen_item('{"id":"0"}',rows),rows[0])
        self.assertIsNone(chosen_item('{"id":null}',rows))
        for text in ('{"id":0}','{"id":"1"}','{"id":"0","action":"sleep"}','[动作:sleep]'):
            with self.assertRaises(ValueError):chosen_item(text,rows)

    def test_singing_a_named_song_uses_the_same_real_playlist(self):
        from deskpet.chat.actions import recognize_action
        self.assertEqual(recognize_action('唱一下'),'sing')
        with self.window() as (w,remote):
            for text in ('唱一下本地《普通DISCO》', '能不能给我唱一下普通DISCO好吗',
                         '天依，唱《普通DISCO》给我听吧', '来一首普通DISCO'):
                w.input.setPlainText(text);w.send_message()
                self.assertEqual(remote.return_value.start.call_args.args[1][-1]['content'], text)
                before = self.p.start_track.call_count
                w.on_completed('[动作:music_local {"pattern":"普通DISCO"}]好呀。')
                self.assertEqual(self.p.start_track.call_count, before + 1)
                self.p.start_track.assert_called_with(2)
                self.assertIsNone(w.pending)

    def test_switch_source_and_bilibili_collection_are_executable(self):
        from deskpet.chat.actions import recognize_action
        for text in ('切b站','切到B站','换成b站播放','播放b站','给我播放B站歌单'):
            self.assertEqual(recognize_action(text),'music_bilibili',text)
        self.assertEqual(recognize_action('切回本地'),'music_local')
        with self.window() as (w,remote):
            self.p.playback_source='local'
            self.p.bilibili.tracks[1]['title']='【洛天依歌单】华风夏韵，洛水天依'
            w.input.setPlainText('给我播放b站合集');w.send_message()
            self.assertEqual(remote.return_value.start.call_count, 1)
            w.on_completed('[动作:music_bilibili {"pattern":"合集|合辑|歌单|串烧"}]好呀。')
            self.assertEqual(self.p.playback_source,'web')
            self.p._player.pause.assert_called()
            self.assertEqual(self.p.bilibili.current_url,self.p.bilibili.tracks[1]['url'])
            self.assertIn('准备播放B站',w.store.history(w.character)[-1]['content'])

    def test_failed_or_cancelled_intent_request_never_falls_back_to_playback(self):
        with self.window() as (w, remote):
            for failure in ('offline', 'cancel'):
                w.input.setPlainText('唱歌累不累');w.send_message()
                if failure == 'offline':
                    w.on_failed('连接超时')
                else:
                    w.stop()
                w.on_completed('[动作:music_play {"pattern":"普通DISCO"}]好呀。')
                self.assertIsNone(w.pending)
                self.assertEqual(w.input.toPlainText(), '唱歌累不累')
            self.p.start_track.assert_not_called()
            self.p.bilibili.start_process.assert_not_called()
