"""Left-walk routing must share cooldown, interruption and route ownership."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from deskpet.pet.desktop import DesktopPet
from deskpet.pet.behavior import ActionPriority
from deskpet.chat.actions import perform_action
from tests.test_companion_actions import WalkingPet


class CrawlRoutingTests(unittest.TestCase):
    def pet(self):
        pet = WalkingPet()
        pet.live2d_renderer = NS(crawl_available=True, work_available=False)
        pet.panel.settings.setValue = Mock()
        pet.panel.settings.sync = Mock()
        pet.drag_dock_edge = ''
        pet.dock_reveal = 1
        return pet

    def test_threshold_once_per_valid_left_start(self):
        for roll, expected in [(0, 'crawl'), (.249999, 'crawl'), (.25, 'walk'), (.99, 'walk')]:
            pet = self.pet()
            with patch('deskpet.animation.walk_runtime.random.random', return_value=roll) as draw:
                self.assertTrue(pet.start_walk(direction=-1, cycles=2, chat_command=True))
                self.assertEqual(pet.walk_controller.motion, expected)
                for _ in range(5):
                    pet.tick_walk(.05)
                draw.assert_called_once_with()
            self.assertEqual(DesktopPet.display_activity(pet),
                             'crawl' if expected == 'crawl' else 'walk-left')

    def test_manual_automatic_and_api_use_same_routing(self):
        for source in ('manual', 'automatic', 'api', 'chosen-left'):
            pet = self.pet()
            pet.chat_window.visible = source == 'api'
            with patch('deskpet.animation.walk_runtime.random.random', return_value=0), \
                    patch.object(pet.walk_controller._rng, 'choice', return_value=-1):
                if source == 'api':
                    self.assertTrue(perform_action(pet, 'walk_left').executed)
                else:
                    self.assertTrue(pet.start_walk(
                        direction=None if source == 'chosen-left' else -1,
                        cycles=2, automatic=source == 'automatic'))
            self.assertTrue(pet.is_crawl_walk())
            self.assertEqual(pet.behavior.layers[-1].priority,
                             ActionPriority.AUTOMATIC if source == 'automatic' else ActionPriority.USER)

    def test_right_and_missing_model_never_draw_or_crawl(self):
        for direction, available in [(1, True), (-1, False)]:
            pet = self.pet()
            pet.live2d_renderer.crawl_available = available
            with patch('deskpet.animation.walk_runtime.random.random') as draw:
                self.assertTrue(pet.start_walk(direction=direction, cycles=2, chat_command=True))
                draw.assert_not_called()
            self.assertEqual(pet.walk_controller.motion, 'walk')

    def test_crawl_keeps_destination_and_has_only_one_mover(self):
        pet = self.pet()
        pet.behavior.set_mode('listen')
        with patch('deskpet.animation.walk_runtime.random.random', return_value=0):
            self.assertTrue(pet.start_walk(direction=-1, cycles=2, chat_command=True))
        # The original route is 2 * 80 source px * .5 scale = 80 desktop px.
        for _ in range(130):
            pet.tick_walk(.05)
            before = pet.x()
            if pet.is_crawl_walk():
                DesktopPet.tick_crawl_movement(pet, 'crawl')
                self.assertEqual(pet.x(), before)
                self.assertEqual(pet.crawl_elapsed(), pet.walk_controller.elapsed)
        self.assertEqual(pet.x(), 120)
        self.assertFalse(pet.walk_controller.active)
        self.assertEqual(pet.behavior.mode, 'listen')
        self.assertFalse(pet.behavior.layers)

    def test_crawl_stop_redirect_drag_and_cooldown(self):
        pet = self.pet()
        pet.chat_window.visible = False
        with patch('deskpet.animation.walk_runtime.random.random', return_value=0):
            self.assertTrue(pet.start_walk(direction=-1, cycles=2, automatic=True))
        deadline = pet.walk_controller.cooldown_until
        self.assertGreater(deadline, 0)
        self.assertTrue(perform_action(pet, 'stop_walk').executed)
        self.assertFalse(pet.walk_controller.active)
        pet.chat_window.visible = True
        with patch('deskpet.animation.walk_runtime.random.random', return_value=0):
            self.assertTrue(perform_action(pet, 'walk_left').executed)
        self.assertEqual(pet.walk_controller.cooldown_until, deadline)
        self.assertTrue(perform_action(pet, 'walk_right').executed)
        self.assertEqual(pet.walk_controller.motion, 'walk')
        pet.stop_walk()
        with patch('deskpet.animation.walk_runtime.random.random', return_value=0):
            self.assertTrue(perform_action(pet, 'walk_left').executed)
        pet.dragging = True
        pet.tick_walk(.1)
        self.assertFalse(pet.walk_controller.active)
        self.assertFalse(pet.behavior.layers)


if __name__ == '__main__':
    unittest.main()
