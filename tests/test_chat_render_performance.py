"""Small, offline checks for bounded chat document updates."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from deskpet.chat.conversation_view import ConversationView


class ChatRenderPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stream_appends_only_new_text_including_utf16_and_revisions(self):
        view = ConversationView()
        self.addCleanup(view.close)
        view.set_messages([dict(role='user', content='keep history')], ('name', ''))
        changes = []
        view.document().contentsChange.connect(lambda p, r, a: changes.append((p, r, a)))
        text = ''
        for _ in range(100):
            text += '😀x\n'
            view.update_live(text)
        # Qt measures UTF-16 positions: each suffix is four code units.
        self.assertEqual(sum(r for _, r, _ in changes), 0)
        self.assertEqual(sum(a for _, _, a in changes), 400)
        changes.clear()
        view.update_live(text)
        self.assertEqual(changes, [])
        view.update_live('revised 😀 reply')
        view.update_live('revised 😀 reply + suffix')
        self.assertIn('keep history', view.toPlainText())
        self.assertIn('revised 😀 reply + suffix', view.toPlainText())
        self.assertNotIn('😀x', view.toPlainText())

    def test_repeated_sticker_decodes_once_and_frame_dirties_only_images(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image.png'
            image = QImage(8, 8, QImage.Format_RGB32)
            image.fill(0xff123456)
            image.save(str(path))
            item = SimpleNamespace(path=path, title='test', source='', animated=False)
            view = ConversationView()
            self.addCleanup(view.close)
            view.sticker_catalog = SimpleNamespace(get=lambda key: item)
            rows = [dict(role='user', content='history' * 200, stickers=['one'])
                    for _ in range(10)]
            with patch('deskpet.chat.conversation_view.QPixmap', wraps=QPixmap) as decode:
                view.set_messages(rows)
            self.assertEqual(sum(call.args == (str(path),) for call in decode.call_args_list), 1)
            self.assertEqual(len(view._sticker_positions['one']), 10)
            movie = Mock()
            movie.currentPixmap.return_value = view.sticker_frames['one']
            view.sticker_movies['one'] = movie
            document = view.document()
            with patch.object(document, 'markContentsDirty', wraps=document.markContentsDirty) as dirty:
                view._sticker_frame('one', movie)
            self.assertEqual(dirty.call_count, 10)
            self.assertEqual(sum(call.args[1] for call in dirty.call_args_list), 10)
            view.stop_sticker_movies()


if __name__ == '__main__':
    unittest.main()
