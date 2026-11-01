import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication, QWidget
from deskpet.chat.action_protocol import ACTIONS, split_reply, snapshot
from deskpet.chat.prompts import build_messages, parse_reply
from deskpet.pet.behavior import PetBehavior, ActionPriority
from tests.test_companion_actions import WalkingPet
from deskpet.animation.teleport_runtime import TeleportRuntime


class ProtocolTests(unittest.TestCase):
    def test_tags_never_leak_during_stream_or_become_arbitrary_calls(self):
        text='[动作:sleep][温柔]盖好被子啦'
        for end in range(1, len('[动作:sleep]')+1):
            self.assertEqual(parse_reply(text[:end],partial=True)[0],'')
        self.assertEqual(parse_reply(text),('盖好被子啦','温柔'))
        for bad in ('[动作:drag]拖起来', '[动作:run_shell]执行', '[动作:sleep][动作:phone]都做',
                    '举个例子[动作:sleep]', '[动作:__dict__]改配置'):
            body, action, error=split_reply(bad)
            self.assertIsNone(action);self.assertIsNotNone(error)
            self.assertNotIn('[动作',body)
        for action in ACTIONS:
            self.assertEqual(split_reply(f'[动作:{action}]好呀')[1],action)

    def test_action_contract_only_attached_to_explicit_chat(self):
        basic=build_messages('人设','',[],'你好','idle')[0]['content']
        self.assertIn('本轮没有动作接口',basic)
        with_actions=build_messages('人设','',[],'去休息一下','idle',actions=['sleep','wake'])[0]['content']
        self.assertIn('sleep=盖被子睡觉',with_actions)
        self.assertNotIn('teleport=随机',with_actions)


class ApiWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_natural_request_api_action_once_and_late_result_rejected(self):
        from deskpet.chat.window import ChatWindow
        from deskpet.chat.config import ProviderConfig
        with tempfile.TemporaryDirectory() as folder:
            pet=QWidget();pet.panel=NS(data_dir=Path(folder),
                settings=QSettings(str(Path(folder)/'test.ini'),QSettings.IniFormat),store=NS(pet=lambda:{'level':1}))
            pet.character_pack=None;pet.variant='refined';pet.character_name='洛天依'
            pet.behavior=PetBehavior();pet.dragging=pet.petting=pet.playing=False;pet.press_point=None
            pet.live2d_renderer=None;pet.scaled_frames={'sleep':object(),'happy':object()}
            pet.walk_supported=lambda:False
            pet.set_mode=Mock(side_effect=pet.behavior.set_mode);pet.reveal_dock=Mock();pet.react=Mock()
            pet.bubble=NS(say=Mock());pet.show()
            with patch('deskpet.chat.companion_runtime.CompanionRuntime'):
                window=ChatWindow(pet)
                window.config=ProviderConfig(base_url='http://localhost:12345/v1',model='test')
                window.input.setPlainText('今天辛苦了，钻进被窝小睡一阵好不好')
                with patch.object(window,'request_client') as remote:
                    window.send_message()
                    messages=remote.return_value.start.call_args.args[1]
                    self.assertIn('sleep=盖被子睡觉',messages[0]['content'])
                window.on_partial('[动作:sleep][温柔]好呀')
                pet.set_mode.assert_not_called()
                window.on_completed('[动作:sleep][温柔]好呀，这就盖上被子。')
                pet.set_mode.assert_called_once_with('sleep')
                window.on_completed('[动作:sleep]重复响应')
                self.assertEqual(pet.set_mode.call_count,1)
                self.assertNotIn('[动作',window.store.history(window.character)[-1]['content'])
                pet.set_mode.reset_mock()
                window.pending=(window.character,'现在起床好不好')
                window.pending_action_context=snapshot(pet);window.pending_actions=('wake',)
                pet.last_user_interaction=100
                window.on_completed('[动作:wake]这就起来')
                pet.set_mode.assert_not_called()
                self.assertIn('状态已经改变',window.store.history(window.character)[-1]['content'])
                window.shutdown();pet.close()


class TeleportPet(WalkingPet, TeleportRuntime):
    def __init__(self):
        super().__init__();self.init_teleport()
        self.panel.settings.setValue=Mock();self.panel.settings.sync=Mock()
        self.effects=NS(sync=Mock());self.hit_region=QRegion(QRect(0,0,100,200))
    def y(self):return 200


class TeleportCommandTests(unittest.TestCase):
    def test_short_direction_commands_dispatch_real_manual_teleport(self):
        from deskpet.chat.actions import recognize_action, perform_action
        for text, direction in (('往上', -1), ('往下', 1)):
            with self.subTest(text=text):
                pet = TeleportPet()
                pet.auto_teleport_enabled = False
                self.assertTrue(perform_action(pet, recognize_action(text)).executed)
                self.assertTrue(pet.teleport_controller.active)
                self.assertEqual(pet.behavior.action, 'teleport')
                self.assertGreater(direction * (pet.teleport_controller.destination - pet.y()), 0)
                pet.stop_teleport()

    def test_chat_teleport_ignores_passive_setting_cooldown_and_chat_window(self):
        import time
        from deskpet.animation.teleport_controller import TeleportController
        pet=TeleportPet();pet.auto_teleport_enabled=False
        deadline=time.time()+600;pet.teleport_controller=TeleportController(deadline)
        self.assertTrue(pet._start_teleport(automatic=False,direction=-1))
        self.assertLess(pet.teleport_controller.destination,pet.y())
        self.assertEqual(pet.behavior.layers[-1].priority,ActionPriority.USER)
        self.assertEqual(pet.teleport_controller.cooldown_until,deadline)
        pet.bubble.visible=True;pet.tick_teleport(.1)
        self.assertTrue(pet.teleport_controller.active)
        pet.dragging=True;pet.tick_teleport(.1)
        self.assertFalse(pet.teleport_controller.active)
        self.assertFalse(pet.teleport_from_chat)
        pet.dragging=False
        self.assertTrue(pet._start_teleport(automatic=False,direction=1))
        self.assertGreater(pet.teleport_controller.destination,pet.y())
        pet.stop_teleport()
        self.assertFalse(pet._start_teleport())
