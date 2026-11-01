import unittest
from deskpet.chat.companion import CompanionCoordinator, CompanionState


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.c = CompanionCoordinator(enabled=True, clock=lambda: self.now)
        self.state = CompanionState(idle_seconds=60)

    def test_cancel_discards_late_reply(self):
        ticket = self.c.request(self.state)
        self.c.cancel()
        self.assertFalse(self.c.deliver(ticket, self.state))

    def test_busy_modes_and_user_actions_block(self):
        for state in (CompanionState(mode='sleep', idle_seconds=60),
                      CompanionState(dragging=True, idle_seconds=60),
                      CompanionState(chat_busy=True, idle_seconds=60),
                      CompanionState(has_action=True, idle_seconds=60)):
            self.assertIsNone(self.c.request(state))

    def test_cooldown_after_cancel(self):
        self.c.request(self.state)
        self.c.cancel()
        self.assertIsNone(self.c.request(self.state))
        self.now = 181
        self.assertIsNotNone(self.c.request(self.state))

    def test_action_second_check_and_whitelist(self):
        ticket = self.c.request(self.state)
        self.assertTrue(self.c.deliver(ticket, self.state))
        calls = []
        self.assertFalse(self.c.execute_action(ticket, 'exec', lambda: self.state, calls.append))
        self.assertFalse(self.c.execute_action(ticket, 'happy',
            lambda: CompanionState(dragging=True, idle_seconds=60), calls.append))
        self.assertEqual(calls, [])

    def test_mode_off_invalidates(self):
        ticket = self.c.request(self.state)
        self.c.set_enabled(False)
        self.assertFalse(self.c.deliver(ticket, self.state))

if __name__ == '__main__':
    unittest.main()
