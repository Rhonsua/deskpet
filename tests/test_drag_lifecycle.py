"""Lost mouse grabs must never turn a temporary lift into a saved activity."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from desktop_pet import DesktopPet
from drag_motion import DragSway
from pet_behavior import PetBehavior


class DragLifecycleTests(unittest.TestCase):
    def subject(self, mode):
        behavior = PetBehavior(mode)
        behavior.tick(3)
        behavior.begin_drag()
        behavior.tick(2)
        sway = DragSway()
        sway.move(40, .1)
        sway.step(.1)
        return SimpleNamespace(dragging=True, press_point=object(), behavior=behavior,
            hold_timer=Mock(), click_timer=Mock(), drag_dock_edge='left',
            drag_sample_point=object(), drag_sway=sway, setCursor=Mock(),
            live2d_frame_key=('lift', 2), update=Mock())

    def test_interrupted_grab_restores_each_saved_mode_and_clears_input(self):
        for mode in ('idle', 'sleep', 'phone', 'sing', 'listen'):
            with self.subTest(mode=mode):
                pet = self.subject(mode)
                DesktopPet.cancel_interrupted_drag(pet)
                self.assertEqual(pet.behavior.mode, mode)
                self.assertEqual(pet.behavior.mode_elapsed, 3)
                self.assertFalse(pet.behavior.layers)
                self.assertFalse(pet.dragging)
                self.assertIsNone(pet.press_point)
                self.assertIsNone(pet.drag_sample_point)
                self.assertIsNone(pet.live2d_frame_key)
                self.assertEqual(pet.drag_dock_edge, '')
                self.assertEqual(pet.drag_sway.angle, 0)
                pet.hold_timer.stop.assert_called_once()
                pet.click_timer.stop.assert_called_once()
                DesktopPet.cancel_interrupted_drag(pet)
                pet.update.assert_called_once()

    def test_interruption_preserves_underlying_timed_reaction(self):
        pet = self.subject('sleep')
        pet.behavior.end_drag(landing=False)
        pet.behavior.react('eat', 2)
        pet.behavior.tick(.5)
        pet.behavior.begin_drag()
        DesktopPet.cancel_interrupted_drag(pet)
        self.assertEqual(pet.behavior.activity, 'eat')
        self.assertEqual(pet.behavior.layers[-1].remaining, 1.5)
        pet.behavior.tick(1.5)
        self.assertEqual(pet.behavior.activity, 'sleep')


if __name__ == '__main__':
    unittest.main()
