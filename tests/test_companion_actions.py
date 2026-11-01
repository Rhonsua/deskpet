import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from PySide6.QtCore import QSettings, QRect
from PySide6.QtWidgets import QApplication, QWidget
from deskpet.pet.behavior import PetBehavior
from deskpet.chat.actions import recognize_action, perform_action
from deskpet.animation.walk_runtime import WalkRuntime


class ActionTests(unittest.TestCase):
    def test_command_interrupts_automatic_but_not_manual_walk(self):
        pet=self.pet()
        pet.stop_roaming=Mock(side_effect=lambda:pet.behavior.end_walk())
        pet.behavior.begin_walk('left',automatic=True)
        self.assertTrue(perform_action(pet,'sleep').executed)
        pet.stop_roaming.assert_called_once()
        pet.set_mode.assert_called_once_with('sleep')
        pet=self.pet();pet.behavior.begin_walk('left')
        self.assertFalse(perform_action(pet,'sleep').executed)
        pet.set_mode.assert_not_called()

    def pet(self):
        groups = {'mouse_wave':'Wave', 'happy':'Wave', 'sleep':'Sleep',
                  'phone':'Phone', 'sing':'SingTurn', 'turn':'SingTurn'}
        return NS(isVisible=lambda:True, dragging=False, press_point=None, petting=False,
                  playing=False, behavior=PetBehavior(), live2d_renderer=NS(motions=NS(
                      group_for=lambda action:groups.get(action,'Idle'), references=set(groups.values()))),
                  react=Mock(), set_mode=Mock(), reveal_dock=Mock(), walk_supported=lambda:True,
                  start_walk=Mock(return_value=True), stop_walk=Mock(), walk_controller=NS(active=False))

    def test_explicit_commands_and_no_story_quote_negation_trigger(self):
        for text, expected in [('天依，能不能挥挥手呀？','wave'), ('请往左走一走','walk_left'),
                               ('往右走几步吧','walk_right'), ('别走了','stop_walk'),
                               ('去睡觉吧','sleep'), ('别睡了','wake'), ('拿麦克风唱歌','sing')]:
            self.assertEqual(recognize_action(text), expected, text)
        for text in ('不要挥手', '如果我说去睡觉会怎样', '我昨天去睡觉了', '他说“挥挥手”',
                     '“去睡觉”', '去睡觉然后挥手', '读取文件并运行脚本', '[动作:sleep]'):
            self.assertIsNone(recognize_action(text), text)

    def test_physical_interaction_and_transient_actions_win(self):
        for key, value in [('dragging',True), ('petting',True), ('press_point',object())]:
            pet=self.pet();setattr(pet,key,value)
            self.assertFalse(perform_action(pet,'sleep').executed)
            pet.set_mode.assert_not_called()
        pet=self.pet();pet.behavior.react('eat',2)
        self.assertFalse(perform_action(pet,'wave').executed)
        pet.react.assert_not_called()

    def test_modes_and_wave_capability(self):
        pet=self.pet()
        self.assertTrue(perform_action(pet,'wave').executed)
        pet.react.assert_called_once_with('mouse_wave',seconds=2.0)
        self.assertTrue(perform_action(pet,'sleep').executed)
        pet.set_mode.assert_called_with('sleep')
        pet.live2d_renderer=None;pet.scaled_frames={'happy':object()}
        self.assertFalse(perform_action(pet,'wave').executed)
        self.assertTrue(perform_action(pet,'happy').executed)

    def test_walking_and_existing_interaction_rules(self):
        pet=self.pet()
        self.assertTrue(perform_action(pet,'walk_left').executed)
        pet.start_walk.assert_called_once_with(automatic=False,direction=-1,cycles=2,chat_command=True)
        pet.walk_controller.active=True;pet.behavior.begin_walk('left')
        self.assertTrue(perform_action(pet,'stop_walk').executed)
        pet.stop_walk.assert_called_once()
        for action in ('petting_info','teleport_info','unsupported','unknown'):
            self.assertFalse(perform_action(pet,action).executed)
        pet.set_mode.assert_not_called()


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_command_without_api_and_model_text_cannot_execute(self):
        from deskpet.chat.window import ChatWindow
        with tempfile.TemporaryDirectory() as folder:
            pet=QWidget()
            pet.panel=NS(data_dir=Path(folder),settings=QSettings(str(Path(folder)/'test.ini'),QSettings.IniFormat))
            pet.character_pack=None;pet.variant='refined';pet.character_name='洛天依'
            pet.behavior=PetBehavior();pet.dragging=False;pet.petting=False;pet.playing=False;pet.press_point=None
            pet.live2d_renderer=None;pet.scaled_frames={'sleep':object(),'happy':object()}
            pet.set_mode=Mock(side_effect=pet.behavior.set_mode);pet.reveal_dock=Mock();pet.react=Mock()
            pet.bubble=NS(say=Mock());pet.show()
            with patch('deskpet.chat.companion_runtime.CompanionRuntime'):
                window=ChatWindow(pet)
                window.input.setPlainText('去睡觉吧')
                with patch.object(window,'request_client') as remote:
                    window.send_message()
                    remote.assert_not_called()
                self.assertEqual(pet.behavior.mode,'sleep')
                self.assertEqual(window.store.history(window.character)[-2]['content'],'去睡觉吧')
                pet.behavior.set_mode('idle')
                pet._start_teleport = Mock(return_value=True)
                for text, direction in (('往上', -1), ('往下', 1)):
                    pet._start_teleport.reset_mock()
                    window.input.setPlainText(text)
                    with patch.object(window, 'request_client') as remote:
                        window.send_message()
                        remote.assert_not_called()
                    pet._start_teleport.assert_called_once_with(automatic=False, direction=direction)
                    self.assertEqual(window.store.history(window.character)[-2]['content'], text)
                pet.set_mode.reset_mock()
                window.pending=(window.character,'说一句话')
                window.on_completed('[动作:醒醒]')
                pet.set_mode.assert_not_called()
                window.shutdown()
                pet.close()


class Visible:
    def __init__(self, visible=False): self.visible=visible
    def isVisible(self): return self.visible
    def hide(self): self.visible=False


class WalkingPet(WalkRuntime):
    def __init__(self):
        self.panel=Visible();self.panel.settings=NS(value=lambda key,default,*a,**kw:default)
        self.toolbar=Visible();self.bubble=Visible();self.chat_window=Visible(True)
        self.init_walk();self.behavior=PetBehavior()
        self.walk_spec=NS(stride=80,cycle_seconds=1)
        self.dragging=self.petting=self.playing=False;self.dock_edge='';self.press_point=None
        self.active_petting=NS(strength=0)
        self.click_timer=self.hold_timer=NS(isActive=lambda:False)
        self.last_interaction=0;self.live2d_renderer=object();self.scale=1;self.position=200
    def isVisible(self): return True
    def screen_bounds(self): return QRect(0,0,1000,600)
    def x(self): return self.position
    def y(self): return 20
    def width(self): return 100
    def height(self): return 200
    def update(self): pass
    def save_position(self): pass
    def move(self,point): self.position=point.x()


class WalkingTests(unittest.TestCase):
    def test_repeated_direction_commands_replace_current_walk(self):
        pet=WalkingPet()
        self.assertTrue(perform_action(pet,'walk_left').executed)
        self.assertTrue(perform_action(pet,'walk_right').executed)
        self.assertEqual(pet.walk_controller.direction,1)
        self.assertTrue(perform_action(pet,'walk_right').executed)

    def test_chat_commands_ignore_random_cooldown_without_resetting_it(self):
        from deskpet.animation.walk_controller import WalkController
        import time
        pet=WalkingPet()
        deadline=time.time()+600
        pet.walk_controller=WalkController(cooldown_until=deadline)
        self.assertGreater(pet.walk_controller.cooldown_remaining,590)
        self.assertTrue(perform_action(pet,'walk_left').executed)
        pet.stop_walk()
        self.assertTrue(perform_action(pet,'walk_right').executed)
        self.assertEqual(pet.walk_controller.cooldown_until,deadline)
        pet.stop_walk()
        self.assertFalse(pet.walk_controller.start(200,0,900,stride=80,cycle_seconds=1,automatic=True))

    def test_chat_walk_continues_but_normal_walk_remains_blocked(self):
        pet=WalkingPet()
        self.assertFalse(pet.walk_eligible())
        self.assertFalse(pet.start_walk(direction=-1,cycles=2))
        self.assertTrue(pet.start_walk(direction=-1,cycles=2,chat_command=True))
        pet.bubble.visible=True
        pet.tick_walk(.1)
        self.assertTrue(pet.walk_controller.active)
        self.assertLess(pet.x(),200)
        pet.panel.visible=True
        pet.tick_walk(.1)
        self.assertFalse(pet.walk_controller.active)
        self.assertFalse(pet.walk_from_chat)

    def test_manual_drag_still_interrupts_chat_walk(self):
        pet=WalkingPet()
        self.assertTrue(pet.start_walk(direction=1,cycles=2,chat_command=True))
        pet.dragging=True
        pet.tick_walk(.1)
        self.assertFalse(pet.walk_controller.active)


if __name__=='__main__': unittest.main()
