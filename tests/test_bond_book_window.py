import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QCoreApplication
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.widget import BondWidget, render_memory_card

class BookWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.store=BondStore(':memory:');self.mod=SimpleNamespace(store=self.store,active=True,games=[],analysis_owner=None,events=SimpleNamespace(summary=lambda:'',active=None),services=SimpleNamespace(),guess=lambda:None,weekly_show=lambda:None)
        self.origin=QDialog();layout=QVBoxLayout(self.origin);self.widget=BondWidget(self.mod,self.origin);layout.addWidget(self.widget);self.origin.show();self.app.processEvents()
    def tearDown(self):
        if self.widget._book_window:self.widget._book_window.close()
        self.origin.close();self.app.processEvents();self.store.close()
    def test_transparent_drag_return_and_close(self):
        self.widget.tabs.setCurrentIndex(2);self.app.processEvents();book=self.widget._book_window
        self.assertFalse(self.origin.isVisible());self.assertTrue(book.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(book.grab().toImage().pixelColor(0,0).alpha(),0)
        canvas=self.widget.album.canvas;local=canvas._book_rect.center().toPoint();global_pos=canvas.mapToGlobal(local);start=book.pos()
        press=QMouseEvent(QEvent.MouseButtonPress,QPointF(local),QPointF(local),QPointF(global_pos),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
        canvas.mousePressEvent(press)
        move=QMouseEvent(QEvent.MouseMove,QPointF(local+QPoint(25,20)),QPointF(local+QPoint(25,20)),QPointF(global_pos+QPoint(25,20)),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
        canvas.mouseMoveEvent(move)
        release=QMouseEvent(QEvent.MouseButtonRelease,QPointF(local+QPoint(25,20)),QPointF(local+QPoint(25,20)),QPointF(global_pos+QPoint(25,20)),Qt.LeftButton,Qt.NoButton,Qt.NoModifier)
        canvas.mouseReleaseEvent(release)
        self.assertEqual(book.pos(),start+QPoint(25,20))
        self.widget.album.back.click();self.app.processEvents();self.assertTrue(self.origin.isVisible());self.assertEqual(self.widget.tabs.currentIndex(),0)
        self.widget.tabs.setCurrentIndex(2);self.app.processEvents();self.widget.album.close_book.click();self.app.processEvents()
        self.assertFalse(self.origin.isVisible());self.assertIsNone(self.widget._book_window);self.assertEqual(self.widget.tabs.currentIndex(),0)

    def test_export_long_visible_record_preserves_text_and_original_date(self):
        body = ('自己的留笺，含 🎵 和 English。\n'*25) + '最后一句也在。'
        self.store.card('diary:export','一封长信',body)
        self.widget.tabs.setCurrentIndex(2);self.widget.album.set_section('days')
        self.widget.album.turn(1)
        stamp = next(row['at'][:10] for row in self.store.memories() if row['id']=='diary:export')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'留笺.png'
            with patch('deskpet.mods.bond.widget.QInputDialog.getItem',side_effect=lambda parent,t,l,opts,*a:(opts[0],True)), \
                    patch('deskpet.mods.bond.widget.QFileDialog.getSaveFileName',return_value=(str(path),'PNG')), \
                    patch('deskpet.mods.bond.widget.QMessageBox.information'), \
                    patch('deskpet.mods.bond.widget.render_memory_card',wraps=render_memory_card) as render:
                self.widget.export_card()
            self.assertEqual(render.call_args.args[:3], ('一封长信',body,'收录于 '+stamp))
            image=QImage(str(path))
            self.assertFalse(image.isNull())
            self.assertGreater(image.height(),1000)

if __name__=='__main__':unittest.main()
