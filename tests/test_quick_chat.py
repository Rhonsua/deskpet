"""The pet composer must share conversation state without losing either draft."""
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from deskpet.chat.quick_input import QuickChatInput
from tests import test_music_ai_choice as fixtures


class QuickChatTests(unittest.TestCase):
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def composer(self):
        with self.window() as (window, remote):
            window.pet.ensure_chat = lambda: window
            window.pet.chat_window = window
            window.pet.stop_roaming = Mock()
            composer = QuickChatInput(window.pet)
            composer.show()
            try:
                yield composer, window, remote
            finally:
                window.stop()
                composer.close()
                composer.deleteLater()

    def test_enter_sends_hidden_companion_with_shared_history_and_keeps_full_draft(self):
        with self.composer() as (composer, window, remote):
            window.input.setPlainText('完整窗口里尚未发送的内容')
            window.store.add_turn(window.character, '你好', '你好呀')
            composer.input.setText('今天很开心')
            QTest.keyClick(composer.input, Qt.Key.Key_Return)
            self.assertFalse(window.isVisible())
            self.assertEqual(composer.input.text(), '')
            self.assertEqual(window.input.toPlainText(), '完整窗口里尚未发送的内容')
            self.assertTrue(composer.input.isReadOnly())
            messages = remote.return_value.start.call_args.args[1]
            self.assertEqual(messages[-1]['content'], '今天很开心')
            self.assertTrue(any(row['content'] == '你好呀' for row in messages))
            window.on_completed('好呀，我们一起听歌吧', companion_reply=True)
            self.assertEqual(window.store.history(window.character)[-2]['content'], '今天很开心')
            self.assertFalse(composer.input.isReadOnly())
            self.assertEqual(composer.pending_text, '')
            window.pet.bubble.say.assert_called_once()

    def test_failed_request_restores_quick_input_without_overwriting_full_draft(self):
        with self.composer() as (composer, window, _):
            window.input.setPlainText('另一个草稿')
            composer.input.setText('今天好吗')
            composer.send()
            window.on_failed('连接超时')
            self.assertEqual(composer.input.text(), '今天好吗')
            self.assertEqual(window.input.toPlainText(), '另一个草稿')
            self.assertIn('连接超时', composer.status.text())
            self.assertEqual(window.store.history(window.character), [])
            self.assertTrue(composer.send_button.isEnabled())

    def test_missing_config_keeps_message_and_reports_actionable_error(self):
        with self.composer() as (composer, window, remote):
            window.config.model = ''
            composer.input.setText('今天好吗')
            composer.send()
            self.assertEqual(composer.input.text(), '今天好吗')
            self.assertTrue(composer.status.text())
            self.assertFalse(window.isVisible())
            self.assertIsNone(window.pending)
            remote.assert_not_called()

    def test_song_command_waits_for_api_intent_then_plays(self):
        with self.composer() as (composer, window, remote):
            composer.input.setText('播放本地普通DISCO')
            composer.send()
            self.assertEqual(remote.return_value.start.call_count, 1)
            self.p.start_track.assert_not_called()
            self.assertTrue(composer.pending_text)
            window.on_completed('[动作:music_local {"pattern":"普通DISCO"}]好呀。')
            self.p.start_track.assert_called_once_with(2)
            self.assertEqual(composer.pending_text, '')
            self.assertEqual(composer.input.text(), '')
            self.assertIsNone(window.pending)

    def test_pending_full_chat_is_not_replaced_by_quick_input(self):
        with self.composer() as (composer, window, remote):
            window.input.setPlainText('今天好吗')
            window.send_message()
            composer.input.setText('另一条消息')
            composer.send()
            self.assertEqual(composer.input.text(), '另一条消息')
            self.assertEqual(window.pending[1], '今天好吗')
            self.assertEqual(remote.return_value.start.call_count, 1)

    def test_full_window_send_button_still_sends_its_own_input(self):
        with self.composer() as (_, window, remote):
            window.input.setPlainText('今天好吗')
            window.send_button.click()
            self.assertEqual(window.pending[1], '今天好吗')
            self.assertEqual(window.input.toPlainText(), '')
            self.assertEqual(remote.return_value.start.call_count, 1)

    def test_voice_delivery_keeps_composer_busy_until_published(self):
        with self.composer() as (composer, window, _):
            callbacks = []
            with patch.object(window.speech, 'set_enabled'), patch.object(window.speech, 'speak',
                    side_effect=lambda text, **kw: callbacks.append(kw['deliver']) or True):
                window.speech_toggle.setChecked(True)
                composer.input.setText('今天好吗')
                composer.send()
                window.on_completed('一起听歌吧', companion_reply=True)
                self.assertTrue(composer.input.isReadOnly())
                self.assertTrue(composer.pending_text)
                callbacks[0]()
                self.assertFalse(composer.input.isReadOnly())
                self.assertFalse(composer.pending_text)

    def test_toolbar_keeps_chat_button_and_quick_draft_across_pages(self):
        from deskpet.pet.desktop import PetToolbar
        with self.window() as (window, _):
            pet = window.pet
            for name in ('pat', 'open_chat', 'open_tools'):
                setattr(pet, name, Mock())
            pet.ensure_chat = lambda: window
            pet.panel.store.pet = lambda: dict(level=1, notes=10, xp=0, hunger=70, mood=90)
            toolbar = PetToolbar(pet)
            try:
                toolbar.page('home')
                captions = [button.text() for button in toolbar.findChildren(QPushButton)]
                self.assertIn('和我聊天', captions)
                self.assertNotIn('一起加油吧', captions)
                toolbar.quick_chat.input.setText('还没写完的消息')
                toolbar.page('food')
                toolbar.page('home')
                QApplication.processEvents()
                self.assertEqual(toolbar.quick_chat.input.text(), '还没写完的消息')
            finally:
                toolbar.close()
                toolbar.deleteLater()


if __name__ == '__main__':
    unittest.main()
