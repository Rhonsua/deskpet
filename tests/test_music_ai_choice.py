import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QWidget
from tests.test_companion_music import MusicTests
from deskpet.chat.music_actions import explicit_song, chosen_item


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

    def test_explicit_requests_are_real_searches_not_model_claims(self):
        for text in ('播放反乌托邦','请播放本地《流光》','播放B站普通DISCO'):
            self.assertIsNotNone(explicit_song(text))
        self.assertEqual(explicit_song('请播放本地《流光》。')[1]['pattern'], '流光')
        for text in ('昨天我播放流光','不要播放流光','如果播放流光会怎样','他说“播放流光”'):
            self.assertIsNone(explicit_song(text))
        with self.window() as (w,remote):
            w.input.setPlainText('播放本地普通DISCO');w.send_message()
            remote.assert_not_called();self.p.start_track.assert_called_once_with(2)
            self.assertIn('普通DISCO',w.store.history(w.character)[-1]['content'])
            w.input.setPlainText('播放不存在的歌');w.send_message()
            remote.assert_not_called();self.assertIn('没找到',w.store.history(w.character)[-1]['content'])

    def test_ambiguous_choice_has_no_paths_and_executes_once(self):
        with self.window() as (w,remote):
            w.input.setPlainText('播放流光');w.send_message()
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
        for text in ('唱一下反乌托邦','你给我唱一下反乌托邦','你唱一下反乌托邦','唱首《反乌托邦》','能不能给我唱一下反乌托邦好吗',
                     '天依，唱《反乌托邦》给我听吧','来一首反乌托邦'):
            action,args=explicit_song(text)
            self.assertEqual(action,'music_play',text)
            self.assertEqual(args['pattern'],'反乌托邦',text)
        self.assertEqual(explicit_song('唱一下本地《流光》')[0],'music_local')
        self.assertEqual(recognize_action('唱一下'),'sing')
        for text in ('不要唱反乌托邦','昨天你唱反乌托邦','他说“唱一下反乌托邦”','唱一下'):
            self.assertIsNone(explicit_song(text),text)
        with self.window() as (w,remote):
            w.input.setPlainText('唱一下本地《普通DISCO》');w.send_message()
            remote.assert_not_called();self.p.start_track.assert_called_once_with(2)

    def test_switch_source_and_bilibili_collection_are_executable(self):
        from deskpet.chat.actions import recognize_action
        for text in ('切b站','切到B站','换成b站播放','播放b站','给我播放B站歌单'):
            self.assertEqual(recognize_action(text),'music_bilibili',text)
        self.assertEqual(recognize_action('切回本地'),'music_local')
        self.assertEqual(explicit_song('给我播放b站合集'),('music_bilibili',{'pattern':'合集|合辑|歌单|串烧'}))
        with self.window() as (w,remote):
            self.p.playback_source='local'
            self.p.bilibili.tracks[1]['title']='【洛天依歌单】华风夏韵，洛水天依'
            w.input.setPlainText('给我播放b站合集');w.send_message()
            remote.assert_not_called()
            self.assertEqual(self.p.playback_source,'web')
            self.p._player.pause.assert_called()
            self.assertEqual(self.p.bilibili.current_url,self.p.bilibili.tracks[1]['url'])
            self.assertIn('准备播放B站',w.store.history(w.character)[-1]['content'])
