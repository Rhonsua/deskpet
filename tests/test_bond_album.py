"""Book navigation and factual/long content, without user settings or network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime, timedelta
import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from deskpet.mods.bond.album import MemoryBook, text_pages, make_pages, chapter_for
from deskpet.mods.bond.store import BondStore


class BookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = BondStore(':memory:')
        self.book = MemoryBook(self.store)
        self.book.resize(940,630)
        self.book.show()
        self.app.processEvents()

    def tearDown(self):
        self.book.close()
        self.book.deleteLater()
        self.app.processEvents()
        self.store.close()

    def test_long_unicode_and_multiline_keep_every_character(self):
        text = ('这是有 🎵 的真实回忆。hello / '+'abcd'*50+'\n')*14
        pages = text_pages(text)
        self.assertGreater(len(pages),2)
        self.assertEqual(''.join(line for page in pages for line in page),text.replace('\n',''))
        self.assertTrue(all(len(page)<=11 for page in pages))
        title='一首很长的歌名'*10
        self.assertIn(title,''.join(line for page in make_pages('a',title,'正文') for line in page.lines))

    def test_facts_and_locks_not_fabricated(self):
        self.book.set_section('growth')
        self.assertEqual(len(self.book.current_pages),6)
        self.assertFalse(self.book.current_pages[0].locked)
        self.assertTrue(all(p.locked and p.date=='尚未抵达' for p in self.book.current_pages[1:]))
        self.book.set_section('week')
        self.assertTrue(self.book.current_pages[0].locked)
        self.assertNotIn('这周听了',str(self.book.current_pages))
        self.book.set_section('actions')
        self.assertEqual(self.book.current_pages[0].kind,'empty')

    def test_new_records_preserve_open_record_and_continuation(self):
        now=datetime.now()
        self.store.card('diary:old','长回忆','真实的文字'*160,now)
        self.book.reload();self.book.set_section('days');self.book.turn(1)
        page=self.book.current_pages[self.book.index]
        self.assertGreater(page.part,0)
        self.store.card('diary:new','新回忆','新内容',now+timedelta(seconds=1))
        self.book.reload()
        current=self.book.current_pages[self.book.index]
        self.assertEqual((current.key,current.part),(page.key,page.part))
        self.book.reload()
        self.assertEqual(self.book.current_pages[self.book.index],current)

    def test_narrow_single_page_and_navigation_bounds(self):
        self.book.set_section('growth')
        self.assertEqual(self.book.step,2)
        self.book.turn(1);self.assertEqual(self.book.index,2)
        self.book.resize(550,630);self.app.processEvents()
        self.assertEqual(self.book.step,1)
        self.book.turn(1);self.assertEqual(self.book.index,3)
        for _ in range(2):self.book.turn(1)
        self.assertEqual(self.book.index,5)
        self.book.turn(1)
        self.assertEqual(self.book.section,'actions')
        self.book.turn(-1)
        self.assertEqual(self.book.section,'growth')
        self.assertEqual(self.book.index,5)
        self.book.set_section('cover')
        self.assertEqual(self.book.index,0)
        self.assertFalse(self.book.previous.isEnabled())
        self.book.set_section('week')
        self.assertFalse(self.book.next.isEnabled())
        self.book.hide();self.assertIsNone(self.book.canvas.old)

    def test_record_categories_and_unlocked_week(self):
        self.assertEqual(chapter_for('action:headpat'),'actions')
        self.assertEqual(chapter_for('combo:gentle'),'actions')
        self.assertEqual(chapter_for('song:local:my.mp3:3'),'music')
        self.assertEqual(chapter_for('show:abc'),'music')
        self.assertEqual(chapter_for('birthday:2026'),'days')
        self.store.db.execute('UPDATE state SET affinity=150');self.store.refresh()
        self.book.reload();self.book.set_section('week')
        self.assertFalse(self.book.current_pages[0].locked)
        self.assertIn('本地记录',''.join(self.book.current_pages[0].lines))

    def test_collection_types_dates_counts_and_refresh_are_read_only(self):
        now = datetime(2026, 11, 17, 12, 0)
        self.store.card('action:feed','一起吃点心','照料的文字'*150,now)
        self.store.card('song:test','歌名','真实听歌记录',now)
        self.store.card('show:test','演出票','真实演出记录',now)
        changes = self.store.db.total_changes
        self.book.reload();self.book.set_section('actions')
        self.assertEqual(self.book.current_pages[0].kind,'sticker')
        self.assertEqual(self.book.current_pages[0].date,'2026-11-17')
        self.assertEqual(self.book.record_counts['actions'],1)
        self.assertGreater(len(self.book.current_pages),1)
        self.assertIn('已收录 1 则',self.book.catalogue.text())
        self.book.set_section('music')
        self.assertTrue(all(page.kind=='record' for page in self.book.current_pages))
        self.assertEqual(self.book.record_counts['music'],2)
        for _ in range(3):self.book.reload()
        self.assertEqual(self.store.db.total_changes,changes)

    def test_narrow_keyboard_continuations_and_cover_without_portrait(self):
        self.book.resize(550,630);self.app.processEvents()
        self.book.set_section('growth')
        QTest.keyClick(self.book.canvas,Qt.Key_Right)
        self.assertEqual(self.book.index,1)
        QTest.keyClick(self.book.canvas,Qt.Key_PageDown)
        self.assertEqual(self.book.index,2)
        QTest.keyClick(self.book.canvas,Qt.Key_Home)
        self.assertEqual(self.book.index,0)
        QTest.keyClick(self.book.canvas,Qt.Key_Left)
        self.assertEqual((self.book.section,self.book.index),('cover',1))
        self.book.canvas.portrait = type(self.book.canvas.portrait)()
        self.book.set_section('growth');self.book.set_section('cover')
        self.book.canvas.animation.stop();self.book.canvas._finish()
        self.assertFalse(self.book.grab().isNull())


if __name__=='__main__':unittest.main()
