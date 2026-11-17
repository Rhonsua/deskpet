import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QSignalSpy
from deskpet.mods.bond.album import MemoryBook
from deskpet.mods.bond.store import BondStore

class BookUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_book_controls_and_signals(self):
        store=BondStore(':memory:');book=MemoryBook(store);book.resize(900,760);book.show();self.app.processEvents()
        back=QSignalSpy(book.back_requested);export=QSignalSpy(book.export_requested)
        book.back.click();book.export_button.click();self.assertEqual(back.count(),1);self.assertEqual(export.count(),1)
        book.bookmarks['music'].click();self.assertEqual(book.section,'music')
        for size,step in [((560,500),1),((900,760),2)]:
            book.resize(*size);self.app.processEvents();self.assertEqual(book.step,step)
            for button in [book.back,book.previous,book.next,book.export_button,*book.bookmarks.values()]:
                self.assertTrue(book.canvas.rect().contains(button.geometry()),button.text())
        book.close();store.db.close()

if __name__=='__main__': unittest.main()
