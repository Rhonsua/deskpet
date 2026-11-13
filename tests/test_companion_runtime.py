import unittest
from contextlib import contextmanager
from unittest.mock import Mock
from types import SimpleNamespace as NS
from deskpet.chat.companion_runtime import CompanionRuntime
from deskpet.chat.companion import (CompanionState, saved_proactive_interval,
                                  PROACTIVE_INTERVAL_KEY, proactive_interval_minutes)
from deskpet.chat.store import ChatStore
from tests.test_music_ai_choice import ChoiceTests

class RuntimeTests(unittest.TestCase):
    def runtime(self):
        hidden=NS(isVisible=lambda:False)
        pet=NS(behavior=NS(mode='idle',layers=[]),dragging=False,press_point=None,
               petting=False,dock_edge='',panel=hidden,toolbar=hidden,bubble=hidden,
               playing=False,isVisible=lambda:True)
        window=NS(pending=None,testing=False,input=NS(toPlainText=lambda:''),
                  isVisible=lambda:False,companion_mode_enabled=True,work_panel=NS(is_running=False))
        # Exercise state without constructing a network worker or Qt window.
        runtime=NS(pet=pet,window=window,started=0)
        return runtime

    def test_runtime_admission(self):
        runtime=self.runtime()
        self.assertTrue(CompanionRuntime.state(runtime).allows(45))
        for field,value in [('press_point',object()),('petting',True),('dock_edge','left')]:
            setattr(runtime.pet,field,value)
            self.assertFalse(CompanionRuntime.state(runtime).allows(45))
            setattr(runtime.pet,field,None if field=='press_point' else False)
        runtime.window.work_panel.is_running=True
        self.assertFalse(CompanionRuntime.state(runtime).allows(45))
        runtime.window.work_panel.is_running=False
        runtime.window.companion_mode_enabled=False
        self.assertFalse(CompanionRuntime.state(runtime).allows(45))

    def test_proactive_memory_does_not_forge_user(self):
        store=ChatStore(':memory:')
        store.add_proactive('tianyi','一起安静待一会儿吧。')
        self.assertEqual(store.history('tianyi'),[])
        self.assertIn('一起安静',store.last_proactive('tianyi'))
        store.clear_history('tianyi')
        self.assertEqual(store.last_proactive('tianyi'),'')
        store.close()


class FrequencyTests(unittest.TestCase):
    setUpClass = ChoiceTests.__dict__['setUpClass']
    setUp = ChoiceTests.setUp
    tearDown = ChoiceTests.tearDown
    window = ChoiceTests.window

    @contextmanager
    def real_runtime(self, window):
        runtime = CompanionRuntime(window)
        runtime.timer.stop()
        window.companion_runtime = runtime
        runtime.client.start = Mock()
        self.now = 0
        runtime.coordinator.clock = lambda: self.now
        runtime.state = lambda: CompanionState(idle_seconds=100)
        yield runtime

    def test_control_saves_and_survives_restart(self):
        with self.window() as (w, _), self.real_runtime(w) as runtime:
            self.assertEqual(w.proactive_interval.value(), 5)
            self.assertEqual(runtime.coordinator.cooldown, 300)
            self.assertFalse(w.proactive_interval.isEnabled())
            w.proactive_toggle.setChecked(True)
            self.assertTrue(w.proactive_interval.isEnabled())
            w.proactive_interval.setValue(13)
            self.assertEqual(runtime.coordinator.cooldown, 780)
            self.owner.settings.sync()
        with self.window() as (w, _), self.real_runtime(w) as runtime:
            self.assertEqual(w.proactive_interval.value(), 13)
            self.assertEqual(runtime.coordinator.cooldown, 780)
            w.proactive_toggle.setChecked(False)
            self.assertFalse(w.proactive_interval.isEnabled())
            self.assertEqual(saved_proactive_interval(self.owner.settings), 13)
            w.proactive_toggle.setChecked(True)
            self.assertEqual(w.proactive_interval.value(), 13)
            runtime.client.start.assert_not_called()

    def test_shorter_and_longer_intervals_apply_without_resetting_elapsed_time(self):
        with self.window() as (w, _), self.real_runtime(w) as runtime:
            w.proactive_toggle.setChecked(True)
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 1)
            runtime.cancel()  # A failed/cancelled call still counts for cooldown.
            self.now = 30
            w.proactive_interval.setValue(1)
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 1)
            self.now = 60
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 2)
            runtime.cancel()
            w.proactive_interval.setValue(10)
            self.now = 659
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 2)
            self.now = 660
            runtime.state = lambda: CompanionState(idle_seconds=100, dragging=True)
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 2)
            runtime.state = lambda: CompanionState(idle_seconds=100)
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 3)
            # Missed intervals never create multiple calls in a single tick.
            runtime.tick()
            self.assertEqual(runtime.client.start.call_count, 3)

    def test_editing_interval_keeps_pending_speech_and_idle_gate(self):
        with self.window() as (w, _), self.real_runtime(w) as runtime:
            w.proactive_toggle.setChecked(True)
            runtime.state = lambda: CompanionState(idle_seconds=44)
            w.proactive_interval.setValue(1)
            runtime.tick()
            runtime.client.start.assert_not_called()
            runtime.state = lambda: CompanionState(idle_seconds=100)
            runtime.tick()
            ticket = runtime.ticket
            marker = Mock()
            runtime.voice_delivery = marker
            runtime.voice_active = True
            from unittest.mock import patch
            with patch.object(w.speech, 'stop') as stop:
                w.proactive_interval.setValue(20)
                self.assertIs(runtime.ticket, ticket)
                self.assertIs(runtime.voice_delivery, marker)
                self.assertTrue(runtime.voice_active)
                marker.assert_not_called()
                stop.assert_not_called()

    def test_legacy_and_invalid_values_load_safely(self):
        for value in (None, '', 'broken', float('inf'), True):
            self.assertEqual(proactive_interval_minutes(value), 5)
        self.assertEqual(proactive_interval_minutes(-100), 1)
        self.assertEqual(proactive_interval_minutes(1000000), 120)
        self.owner.settings.setValue(PROACTIVE_INTERVAL_KEY, 'broken')
        with self.window() as (w, _), self.real_runtime(w) as runtime:
            self.assertEqual(w.proactive_interval.value(), 5)
            self.assertEqual(runtime.coordinator.cooldown, 300)
