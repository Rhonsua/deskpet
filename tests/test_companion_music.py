import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QSettings
from deskpet.chat.music_actions import perform, search
from deskpet.chat.action_protocol import split_reply, parameters
from deskpet.chat.prompts import parse_reply
from deskpet.music.tools.library import MusicLibrary, PlaybackQueue


class MusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from deskpet.app import MusicPanel
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.owner=QWidget()
        self.owner.settings=QSettings(str(root/'test.ini'),QSettings.IniFormat)
        self.owner.volume=NS(value=lambda:60)
        from deskpet.music.players.bilibili_player import BilibiliPlayer
        web=BilibiliPlayer(self.owner);web.start_process=Mock()
        web.tracks=[{'url':'https://www.bilibili.com/video/BV1xx411c7mD/','title':'流光'},
                    {'url':'https://www.bilibili.com/video/BV1yy411c7mD/','title':'普通DISCO'}]
        web.render()
        library=MusicLibrary();self.local=[]
        for name in ('流光','流光现场','普通DISCO'):
            path=root/(name+'.mp3');path.write_bytes(b'fixture');self.local.append(str(path))
        library.add(self.local)
        pet=NS(music_companion=NS(preparation=NS(pending=False,cancel=Mock())),playing=False)
        class Panel:
            @property
            def paths(self):return self.library.paths
            @property
            def player(self):return self._player
        panel=Panel();panel.pet=pet;pet.panel=panel;self.pet=pet;self.p=panel
        panel.settings=self.owner.settings
        panel.library=library;panel.bilibili=web;panel.playback_source='local'
        panel.queue=PlaybackQueue();panel.queue_owner='';panel.failed_paths=set();panel.cloud_player=None
        panel.autoplay_requested=False;panel._player=Mock()
        panel.list=NS(currentRow=lambda:0);panel.current_path=Mock(return_value='')
        panel.render_library=Mock();panel.store_library=Mock();panel.ensure_audio=Mock();panel.toggle=Mock()
        panel.start_track=Mock(return_value=True);panel.step=Mock()
        panel.activate_local=MusicPanel.activate_local.__get__(panel)
        panel.activate_web=MusicPanel.activate_web.__get__(panel)
        panel.play_row=MusicPanel.play_row.__get__(panel)
        web.starting.connect(panel.activate_web)

    def tearDown(self):
        self.p.bilibili.watchdog.stop();self.owner.close();self.owner.deleteLater()
        self.app.processEvents();self.temp.cleanup()

    def test_regex_selects_exact_track_and_arbitrates_sources(self):
        self.p.playback_source='web'
        result=perform(self.pet,'music_local',{'pattern':'^普通DISCO$'})
        self.assertTrue(result.executed);self.assertEqual(self.p.playback_source,'local')
        self.p.start_track.assert_called_once_with(2)
        self.assertEqual(self.p.queue.paths,self.local)
        result=perform(self.pet,'music_bilibili',{'pattern':'^流光$'})
        self.assertTrue(result.executed);self.assertEqual(self.p.playback_source,'web')
        self.p._player.pause.assert_called()
        self.assertEqual(self.p.bilibili.current_url,self.p.bilibili.tracks[0]['url'])

    def test_ambiguous_missing_invalid_and_deleted_do_not_start_music(self):
        from deskpet.chat.music_actions import MusicChoice
        for action,params in [('music_play',{'pattern':'^流光$'}),
                              ('music_local',{'pattern':'流光|普通DISCO'})]:
            with self.assertRaises(MusicChoice):
                perform(self.pet,action,params)
        for action,params in [('music_local',{'pattern':'不存在'}),
                              ('music_local',{'pattern':'['})]:
            self.assertFalse(perform(self.pet,action,params).executed)
        Path(self.local[2]).unlink()
        self.assertFalse(perform(self.pet,'music_local',{'pattern':'^普通DISCO$'}).executed)
        self.p.start_track.assert_not_called();self.p.bilibili.start_process.assert_not_called()

    def test_playlist_selection_and_duplicate_file_dedup(self):
        old=self.p.library.active_id
        second=self.p.library.create('收藏');self.p.library.add([self.local[2]])
        self.assertEqual(len(search(self.p,'^普通DISCO$',source='local')),1)
        self.p.library.active_id=old
        self.assertTrue(perform(self.pet,'music_local',{'playlist':'收藏','pattern':'DISCO'}).executed)
        self.assertEqual(self.p.library.active_id,second)
        self.p.start_track.assert_called_once_with(0)

    def test_pause_is_idempotent_including_preparation_and_web_cold_start(self):
        self.p.autoplay_requested=True;self.pet.music_companion.preparation.pending=True
        perform(self.pet,'music_pause');perform(self.pet,'music_pause')
        self.assertFalse(self.p.autoplay_requested);self.assertEqual(self.p._player.pause.call_count,2)
        self.p.toggle.assert_not_called()
        self.assertTrue(perform(self.pet,'music_bilibili').executed)
        self.assertIsNotNone(self.p.bilibili.pending_load)
        perform(self.pet,'music_pause');perform(self.pet,'music_pause')
        self.assertFalse(self.p.bilibili.pending_load['autoplay'])
        perform(self.pet,'music_resume')
        self.assertTrue(self.p.bilibili.pending_load['autoplay'])

    def test_search_timeout_is_handled_without_playback(self):
        with patch('regex.compile') as compile:
            compile.return_value.search.side_effect=TimeoutError()
            result=perform(self.pet,'music_local',{'pattern':'(a+)+$'})
        self.assertFalse(result.executed);self.assertIn('耗时',result.message)
        self.p.start_track.assert_not_called()

    def test_optional_regex_envelope_never_leaks_in_stream(self):
        text='[动作:music_bilibili {"pattern":"^[流光]+$"}][开心]好呀'
        envelope_end=text.index('}]')+2
        for length in range(1,envelope_end+1):
            self.assertEqual(parse_reply(text[:length],partial=True)[0],'')
        self.assertEqual(split_reply(text)[1],'music_bilibili')
        self.assertEqual(parameters(text),{'pattern':'^[流光]+$'})
        for bad in ('[动作:music_local {"path":"C:/secret.mp3"}]好',
                    '[动作:sleep {"pattern":"test"}]好',
                    '[动作:music_local {"pattern":3}]好'):
            self.assertIsNotNone(split_reply(bad)[2])

    def test_window_api_song_selection_and_restore_button(self):
        from deskpet.chat.window import ChatWindow
        from deskpet.chat.config import ProviderConfig
        from deskpet.pet.behavior import PetBehavior
        pet=QWidget();pet.panel=self.p;self.p.pet=pet
        self.p.data_dir=Path(self.temp.name);self.p.settings=self.owner.settings
        self.p.store=NS(pet=lambda:{'level':1})
        pet.music_companion=None;pet.character_pack=None;pet.variant='refined';pet.character_name='洛天依'
        pet.behavior=PetBehavior();pet.dragging=pet.petting=pet.playing=False;pet.press_point=None
        pet.live2d_renderer=None;pet.scaled_frames={'sleep':object(),'happy':object()}
        pet.walk_supported=lambda:False;pet.stop_roaming=Mock()
        pet.set_mode=Mock(side_effect=pet.behavior.set_mode);pet.reveal_dock=Mock();pet.react=Mock()
        pet.bubble=NS(say=Mock());pet.show()
        with patch('deskpet.chat.companion_runtime.CompanionRuntime'):
            window=ChatWindow(pet)
            window.config=ProviderConfig(base_url='http://localhost:12345/v1',model='test')
            window.input.setPlainText('从本地歌单找一首名字匹配 ^普通DISCO$ 的歌播放')
            with patch.object(window,'request_client') as remote:
                window.send_message()
                self.assertIn('music_local',remote.return_value.start.call_args.args[1][0]['content'])
            window.on_completed('[动作:music_local {"pattern":"^普通DISCO$"}]好呀')
            self.p.start_track.assert_called_once_with(2)
            self.assertIn('普通DISCO',window.store.history(window.character)[-1]['content'])
            pet.behavior.set_mode('phone');pet.work_preview_until=100000000
            window.pending=(window.character,'旧指令');window.pending_action_context=('old',)
            window.restore_button.click()
            self.assertEqual(pet.behavior.mode,'idle')
            self.assertEqual(pet.work_preview_until,0)
            self.assertIsNone(window.pending)
            self.assertEqual(window.input.toPlainText(),'旧指令')
            window.shutdown();pet.close()
