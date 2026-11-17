import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from types import SimpleNamespace
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent,QCoreApplication
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.widget import BondWidget

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

if __name__=='__main__':unittest.main()
