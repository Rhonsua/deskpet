import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication
from deskpet.chat.conversation_view import ConversationView,save_background


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_stream_unicode_replaces_only_assistant_bubble(self):
        view=ConversationView();view.resize(450,400)
        view.set_messages([dict(role='user',content='你好😀 <script>')],('天依','正在想…'))
        view.update_live('你好😀');view.update_live('你好😀\n这是文字和代码 <b>literal</b>')
        text=view.toPlainText()
        self.assertIn('你好😀 <script>',text)
        self.assertIn('<b>literal</b>',text)
        self.assertNotIn('正在想',text)
        view.close()

    def test_background_copy_cover_resize_and_invalid_image_keeps_old(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.png';dest=Path(folder)/'saved.png'
            image=QImage(800,200,QImage.Format_RGB32);image.fill(QColor('#819DAA'));image.save(str(source))
            save_background(source,dest);original=dest.read_bytes();source.unlink()
            view=ConversationView();view.resize(400,500);view.show();self.app.processEvents();view.set_background(dest)
            self.assertGreaterEqual(view.cover.width(),view.viewport().width())
            self.assertGreaterEqual(view.cover.height(),view.viewport().height())
            bad=Path(folder)/'bad.png';bad.write_text('not image')
            with self.assertRaises(ValueError):save_background(bad,dest)
            self.assertEqual(dest.read_bytes(),original)
            view.resize(700,200);self.app.processEvents()
            self.assertGreaterEqual(view.cover.width(),view.viewport().width())
            view.close()
