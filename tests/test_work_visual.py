import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from unittest.mock import Mock
from deskpet.pet.behavior import PetBehavior
from deskpet.animation.work_visual import activity, requested, reconcile, idle_parameters, preempt_automatic


class WorkVisualTests(unittest.TestCase):
    def test_restore_normal_hides_current_work_but_does_not_cancel_task(self):
        from deskpet.chat.actions import perform_action
        pet=self.pet();pet.isVisible=lambda:True;pet.stop_roaming=Mock()
        pet.set_mode=pet.behavior.set_mode
        self.assertTrue(perform_action(pet,'stop_action').executed)
        self.assertTrue(pet.chat_window.work_panel.is_running)
        self.assertIsNone(activity(pet))
        reconcile(pet);self.assertIsNone(activity(pet))
        pet.chat_window.work_panel.is_running=False;reconcile(pet)
        pet.chat_window.work_panel.is_running=True
        self.assertEqual(activity(pet),'work')

    def test_preview_second_click_stops_and_timeout_restores_button(self):
        from deskpet.pet.desktop import DesktopPet
        class Button:
            label='预览工作动作'
            def text(self):return self.label
            def setText(self,value):self.label=value
        pet=self.pet();panel=pet.chat_window.work_panel
        panel.is_running=False;panel.preview_button=Button()
        pet.stop_roaming=Mock();pet.reveal_dock=Mock();pet.update=Mock()
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=100):
            DesktopPet.preview_work_animation(pet)
            self.assertEqual(panel.preview_button.text(),'停止预览')
            self.assertEqual(activity(pet),'work')
            DesktopPet.preview_work_animation(pet)
            self.assertEqual(panel.preview_button.text(),'预览工作动作')
            self.assertIsNone(activity(pet))
            DesktopPet.preview_work_animation(pet)
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=121):
            reconcile(pet)
            self.assertEqual(panel.preview_button.text(),'预览工作动作')
            self.assertIsNone(activity(pet))
        # Stopping a preview never cancels a real task running in the background.
        panel.is_running=True
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=130):
            DesktopPet.preview_work_animation(pet)
            DesktopPet.preview_work_animation(pet)
            self.assertTrue(panel.is_running)
            self.assertEqual(activity(pet),'work')

    def pet(self):
        panel=NS(is_running=True,terminal_state=None,approval_id=None)
        return NS(chat_window=NS(work_panel=panel),live2d_renderer=NS(work_available=True),
                  behavior=PetBehavior(),dragging=False,petting=False,press_point=None,
                  playing=False,dock_edge='',active_petting=NS(strength=0))

    def test_work_wait_complete_and_saved_mode(self):
        pet=self.pet()
        self.assertEqual(activity(pet),'work')
        pet.chat_window.work_panel.approval_id='one'
        self.assertEqual(activity(pet),'work-wait')
        pet.chat_window.work_panel.terminal_state='complete'
        self.assertIsNone(activity(pet))
        self.assertEqual(pet.behavior.mode,'idle')
        self.assertFalse(pet.behavior.layers)

    def test_user_interaction_priority_and_resume(self):
        pet=self.pet()
        for name,value in [('dragging',True),('petting',True),('press_point',object()),('playing',True),('dock_edge','left')]:
            old=getattr(pet,name);setattr(pet,name,value)
            self.assertIsNone(activity(pet),name)
            setattr(pet,name,old)
        pet.behavior.set_mode('sleep')
        self.assertIsNone(activity(pet));self.assertEqual(pet.behavior.mode,'sleep')
        pet.behavior.set_mode('idle')
        pet.behavior.begin_walk('left')
        self.assertIsNone(activity(pet))
        pet.behavior.end_walk()
        self.assertEqual(activity(pet),'work')

    def test_preview_expiry_and_optional_model(self):
        pet=self.pet();pet.chat_window.work_panel.is_running=False;pet.work_preview_until=120
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=100):self.assertEqual(activity(pet),'work')
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=121):self.assertIsNone(activity(pet))
        pet.live2d_renderer.work_available=False
        with patch('deskpet.animation.work_visual.time.monotonic',return_value=100):self.assertIsNone(activity(pet))

    def test_work_preempts_only_automatic_presentation(self):
        pet=self.pet()
        pet.stop_roaming=lambda:(pet.behavior.end_walk(),pet.behavior.end_teleport())
        pet.behavior.begin_walk('left',automatic=True)
        reconcile(pet)
        self.assertEqual(activity(pet),'work')
        pet.behavior.begin_walk('left')
        reconcile(pet)
        self.assertEqual(pet.behavior.activity,'walk-left')
        self.assertIsNone(activity(pet))
        pet.behavior.end_walk()
        pet.behavior.react('happy',1,automatic=True)
        reconcile(pet)
        self.assertEqual(activity(pet),'work')
        pet.behavior.react('eat',2)
        reconcile(pet)
        self.assertEqual(pet.behavior.activity,'eat')
        pet.behavior.begin_drag()
        reconcile(pet)
        self.assertEqual(pet.behavior.activity,'lift')
        pet.behavior.end_drag();pet.behavior.tick(2.65)
        self.assertEqual(activity(pet),'work')

    def test_blink_and_breath_have_independent_time(self):
        self.assertEqual(idle_parameters(0)['ParamWorkBlink'],0)
        self.assertAlmostEqual(idle_parameters(1.15)['ParamWorkBlink'],1)
        self.assertEqual(idle_parameters(1.4)['ParamWorkBlink'],0)
        self.assertNotEqual(idle_parameters(0)['ParamWorkBreath'],idle_parameters(1)['ParamWorkBreath'])
        for t in [i/30 for i in range(300)]:
            self.assertTrue(all(0<=v<=1 for v in idle_parameters(t).values()))

    def test_autonomous_reactions_cannot_replace_user_actions(self):
        pet=self.pet()
        pet.behavior.react('eat',2)
        self.assertFalse(pet.behavior.react('happy',1,automatic=True))
        self.assertEqual(pet.behavior.activity,'eat')
        pet.behavior.set_mode('sleep')
        self.assertFalse(pet.behavior.react('happy',1,automatic=True))
