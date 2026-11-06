"""Deferred text publication around speech completion and cancellation."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS

from PySide6.QtWidgets import QApplication
from tests import test_music_ai_choice as fixtures
from deskpet.chat.companion_runtime import CompanionRuntime
from deskpet.chat.companion import CompanionCoordinator, CompanionState


class SynchronizedReplyTests(unittest.TestCase):
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def voiced(self):
        with self.window() as (window, _):
            window.store.clear_history(window.character)
            callbacks = []
            with patch.object(window.speech, 'set_enabled'), patch.object(window.speech, 'speak',
                    side_effect=lambda text, **kw: callbacks.append(kw.get('deliver')) or True):
                window.speech_toggle.setChecked(True)
                yield window, callbacks

    def complete(self, window):
        window.pending = (window.character, 'hello')
        window.on_completed('reply', companion_reply=True)

    def test_text_store_and_bubble_wait_then_publish_once(self):
        with self.voiced() as (window, callbacks):
            self.complete(window)
            self.assertEqual(window.store.history(window.character), [])
            window.pet.bubble.say.assert_not_called()
            self.assertIsNotNone(window.pending)
            self.assertTrue(callbacks[0]())
            self.assertIsNone(window.pending)
            self.assertEqual(len(window.store.history(window.character)), 2)
            window.pet.bubble.say.assert_called_once()
            self.assertFalse(callbacks[0]())

    def test_stop_reading_and_disable_fall_back_to_text(self):
        for operation in ('stop', 'disable', 'preview'):
            with self.voiced() as (window, callbacks):
                self.complete(window)
                if operation == 'stop': window.stop_speech()
                elif operation == 'disable': window.speech_toggle.setChecked(False)
                else: window.preview_speech()
                self.assertIsNone(window.pending)
                self.assertEqual(len(window.store.history(window.character)), 2)
                self.assertFalse(callbacks[0]())

    def test_cancel_or_work_switch_discards_pending_and_stale_audio(self):
        for operation in ('stop', 'work', 'close'):
            with self.voiced() as (window, callbacks):
                self.complete(window)
                if operation == 'stop': window.stop()
                elif operation == 'work': window.tabs.setCurrentIndex(window.work_index)
                else: window.close()
                self.assertIsNone(window.pending)
                self.assertEqual(window.store.history(window.character), [])
                self.assertFalse(callbacks[0]())
                window.pet.bubble.say.assert_not_called()

    def test_streaming_is_hidden_and_rejected_speech_publishes_text(self):
        with self.voiced() as (window, callbacks):
            window.pending = (window.character, 'hello')
            window.render_history('hello', '')
            window.on_partial('secret partial')
            window.flush_partial()
            self.assertNotIn('secret partial', window._reply_text)
            with patch.object(window.speech, 'speak', return_value=False):
                window.on_completed('reply', companion_reply=True)
            self.assertIsNone(window.pending)
            self.assertEqual(window.store.history(window.character)[-1]['content'], 'reply')

    def test_direct_action_reply_also_waits_for_speech(self):
        with self.voiced() as (window, callbacks):
            window.input.setPlainText('\u6062\u590d\u5e73\u65f6\u72b6\u6001')
            with patch('deskpet.chat.actions.recognize_action', return_value='stop_action'), patch(
                    'deskpet.chat.actions.perform_action', return_value=NS(message='done', executed=True)):
                window.send_message()
            self.assertEqual(window.store.history(window.character), [])
            self.assertTrue(callbacks[0]())
            self.assertEqual(window.store.history(window.character)[-1]['content'], 'done')


class ProactiveVoiceTests(unittest.TestCase):
    def runtime(self):
        runtime = CompanionRuntime.__new__(CompanionRuntime)
        # QObject attributes require initialization even for this isolated flow.
        from PySide6.QtCore import QObject
        QObject.__init__(runtime)
        runtime.enabled = runtime.chat_enabled = True
        runtime.character = 'builtin:luotianyi'
        runtime.coordinator = CompanionCoordinator(enabled=True, minimum_idle=45)
        runtime.current_state = CompanionState(idle_seconds=100)
        runtime.state = lambda: runtime.current_state
        runtime.ticket = runtime.coordinator.request(runtime.state())
        runtime.voice_delivery = None
        runtime.voice_active = False
        callbacks = []
        runtime.window = NS(character=runtime.character, closed=False,
            reply_voice_enabled=lambda: True, store=NS(add_proactive=Mock()),
            speech=NS(speak=lambda text, **kw: callbacks.append(kw['deliver']) or True, stop=Mock()))
        runtime.pet = NS(bubble=NS(say=Mock()))
        runtime.client = NS(cancel=Mock())
        return runtime, callbacks

    def test_proactive_waits_and_rechecks_idle_at_delivery(self):
        for interrupted in (False, True):
            runtime, callbacks = self.runtime()
            runtime._completed('hello')
            runtime.window.store.add_proactive.assert_not_called()
            self.assertTrue(runtime.busy)
            if interrupted: runtime.current_state = CompanionState(idle_seconds=0, dragging=True)
            self.assertEqual(callbacks[0](), not interrupted)
            self.assertFalse(runtime.busy)
            self.assertEqual(runtime.window.store.add_proactive.call_count, 0 if interrupted else 1)

    def test_user_cancellation_stops_synthesis_and_ignores_callback(self):
        runtime, callbacks = self.runtime()
        runtime._completed('hello')
        runtime.cancel()
        runtime.window.speech.stop.assert_called_once()
        self.assertFalse(callbacks[0]())
        runtime.window.store.add_proactive.assert_not_called()


if __name__ == '__main__': unittest.main()
