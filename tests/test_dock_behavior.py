"""Docking must not replace saved state or undo an explicit pull on release."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtCore import QPoint, QRect, QSize
from desktop_pet import DesktopPet
from pet_behavior import PetBehavior


class DockBehaviorTests(unittest.TestCase):
    def test_release_near_edge_after_detaching_does_not_snap_back(self):
        pet = SimpleNamespace(drag_detached_dock=True, scale=1,
            screen_bounds=lambda: QRect(0, 0, 1920, 1040),
            pos=lambda: QPoint(10, 300), size=lambda: QSize(260, 310),
            move=Mock(), save_position=Mock(), fold_timer=Mock(), dock_edge='')
        DesktopPet.snap_to_edge(pet)
        self.assertEqual(pet.dock_edge, '')
        self.assertFalse(pet.drag_detached_dock)
        pet.move.assert_not_called()
        self.assertEqual(pet.dock_target, 1)
        # A new ordinary near-edge release still supports magnetic docking.
        DesktopPet.snap_to_edge(pet)
        self.assertEqual(pet.dock_edge, 'left')

    def test_peek_suppresses_singing_pose_without_changing_intent(self):
        behavior = PetBehavior('sing')
        behavior.playing = True
        pet = SimpleNamespace(behavior=behavior, dock_edge='left',
                              drag_dock_edge='', dock_reveal=0)
        self.assertEqual(DesktopPet.display_activity(pet), 'idle')
        self.assertEqual(behavior.mode, 'sing')
        self.assertTrue(behavior.playing)
        pet.dock_reveal = 1
        self.assertEqual(DesktopPet.display_activity(pet), 'sing')

    def test_resting_pose_is_preserved_after_docked_pickup(self):
        for mode in ('sleep', 'phone'):
            behavior = PetBehavior(mode)
            behavior.begin_drag()
            pet = SimpleNamespace(behavior=behavior, dock_edge='bottom',
                                  drag_dock_edge='bottom', dock_reveal=0)
            self.assertEqual(DesktopPet.display_activity(pet), 'idle')
            behavior.end_drag(landing=False)
            pet.drag_dock_edge = ''
            self.assertEqual(DesktopPet.display_activity(pet), mode)


if __name__ == '__main__':
    unittest.main()
