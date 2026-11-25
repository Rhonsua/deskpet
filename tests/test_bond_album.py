"""Book navigation and factual/long content, without user settings or network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from deskpet.mods.bond.album import MemoryBook, Page, text_pages, make_pages, chapter_for
from deskpet.mods.bond.scrapbook import page_sticker
from deskpet.mods.bond.store import BondStore, CATEGORIES, SCROLL_PIECES


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

    def test_play_unlocks_only_earned_art_and_updates_the_open_puzzle(self):
        self.book.set_section('scroll')
        self.book.canvas.animation.setCurrentTime(self.book.canvas.animation.duration())
        self.app.processEvents()
        reader = self.book.canvas.river
        self.assertTrue(reader.isVisible())
        self.assertEqual(reader.strip.count, 1)
        self.assertFalse(self.store.join_scroll(2))
        reader.set_mode(True)
        self.assertFalse(reader.options)
        today = datetime.now()
        self.store.record('headpat', {}, today)
        self.store.record('headpat', {}, today)
        self.book.reload()
        self.assertEqual(reader.strip.count, 1)
        self.assertEqual(sorted(reader.options), [1, 2])
        self.assertFalse(self.store.join_scroll(3))
        reader.answer(next(i for i, n in enumerate(reader.options) if n != 2))
        self.assertEqual(self.store.scroll_joined(), 1)
        reader.buttons[reader.options.index(2)].click()
        self.assertEqual(self.store.scroll_joined(), 2)
        self.assertEqual(reader.options, [])
        reader.set_mode(False)
        self.assertEqual(reader.strip.count, 2)
        self.book.set_section('art')
        self.assertFalse(reader.isVisible())
        for day in range(4):
            for kind in CATEGORIES:
                self.store.award(kind, today + timedelta(days=day))
        self.book.reload()
        self.book.set_section('scroll')
        self.book.canvas.animation.setCurrentTime(self.book.canvas.animation.duration())
        self.assertEqual(reader.strip.count, SCROLL_PIECES)
        reader.next.click()
        self.assertGreater(reader.strip.horizontalScrollBar().value(), 0)
        reader.set_mode(True)
        for piece in range(3,19):
            self.assertEqual(len(reader.options), len(set(reader.options)))
            self.assertTrue(all(1 <= n <= reader.unlocked for n in reader.options))
            reader.answer(reader.options.index(piece))
        self.assertEqual(self.store.scroll_joined(), 18)
        self.assertFalse(self.store.join_scroll(18))
        self.assertIn('river-scroll-complete', {row['id'] for row in self.store.memories()})
        self.assertEqual(reader.options, [])

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

    def test_back_across_chapters_and_bookmarks_uses_the_earlier_direction(self):
        canvas = self.book.canvas
        for width, last_growth_page in ((940, 4), (550, 5)):
            with self.subTest(width=width):
                self.book.resize(width, 630)
                self.app.processEvents()
                self.book.bookmarks['actions'].click()
                canvas.animation.setCurrentTime(canvas.animation.duration())
                self.book.previous.click()
                self.assertEqual((self.book.section, self.book.index), ('growth', last_growth_page))
                self.assertEqual(canvas.direction, -1)
                self.book.next.click()
                self.assertEqual((self.book.section, self.book.index, canvas.direction), ('actions', 0, 1))
                self.book.bookmarks['cover'].click()
                self.assertEqual((self.book.section, self.book.index, canvas.direction), ('cover', 0, -1))

    def test_corner_stickers_stay_with_the_page_and_fit_its_contents(self):
        canvas = self.book.canvas
        for i in range(3):
            self.store.card(f'diary:sticker{i}', '留笺', '正文')
        self.book.reload()
        cover, title = self.book.pages['cover']
        self.assertIsNone(canvas._margin_sticker(cover))
        first_layout = canvas._margin_sticker(title)
        _, rect = first_layout
        self.assertGreater(rect.top(), canvas._link_rect(title, 2).bottom())
        self.assertLess(rect.bottom(), 481)
        self.book.set_section('growth')
        stage = self.book.current_pages[0]
        self.assertLess(canvas._margin_sticker(stage)[1].bottom(), 455)
        self.book.resize(530, 630)
        self.app.processEvents()
        self.book.reload()
        self.assertEqual(canvas._margin_sticker(title), first_layout)
        with patch('deskpet.mods.bond.album.page_sticker', return_value=(2, True)):
            full = Page('diary:full', '长回忆', lines=('文字',)*11, kind='memory')
            self.assertIsNone(canvas._margin_sticker(full))
            short = Page('song:short', '听歌', lines=('歌曲',), kind='record')
            self.assertGreater(canvas._margin_sticker(short)[1].left(), 320)

    def test_corner_sticker_variety_is_repeatable_across_book_sessions(self):
        def sample():
            return [page_sticker('2026-07-12', f'diary:{i}', 0) for i in range(128)]

        initial = sample()
        self.assertIn(None, initial)
        choices = [choice for choice in initial if choice is not None]
        self.assertEqual({pose for pose, _ in choices}, set(range(8)))
        self.assertEqual({side for _, side in choices}, {False, True})
        page_sticker.cache_clear()
        self.assertEqual(sample(), initial)

    def test_reversing_mid_turn_keeps_the_edge_in_place(self):
        canvas = self.book.canvas
        self.book.set_section('growth')
        canvas.animation.setCurrentTime(canvas.animation.duration())
        self.book.next.click()
        canvas.animation.setCurrentTime(65)
        forward_progress = canvas.progress
        self.assertTrue(0 < forward_progress < 1)
        self.book.previous.click()
        self.assertEqual((self.book.index, canvas.direction), (0, -1))
        self.assertAlmostEqual(canvas.progress, 1-forward_progress)
        canvas.animation.setCurrentTime(canvas.animation.duration())
        self.assertIsNone(canvas.old)

    def test_back_turn_reveals_the_previous_page_from_the_left(self):
        canvas = self.book.canvas
        for width in (550, 940):
            with self.subTest(width=width):
                self.book.resize(width, 630)
                self.app.processEvents()
                self.book.set_section('actions')
                canvas.animation.setCurrentTime(canvas.animation.duration())
                source = canvas.grab().toImage()
                self.book.previous.click()
                canvas.animation.setCurrentTime(45)
                middle = canvas.grab().toImage()
                canvas.animation.setCurrentTime(canvas.animation.duration())
                destination = canvas.grab().toImage()
                area = canvas._book_rect
                ratio = source.devicePixelRatio()
                for x, expected in ((.10, destination), (.62, source)):
                    patch_rect = (round((area.x()+x*area.width())*ratio),
                                  round((area.y()+.13*area.height())*ratio),
                                  round(.25*area.width()*ratio), round(.62*area.height()*ratio))
                    self.assertNotEqual(source.copy(*patch_rect), destination.copy(*patch_rect))
                    self.assertEqual(middle.copy(*patch_rect), expected.copy(*patch_rect))

    def test_home_and_record_links_use_the_destination(self):
        self.book.set_section('growth')
        self.book.next.click()
        QTest.keyClick(self.book.canvas, Qt.Key_Home)
        self.assertEqual((self.book.index, self.book.canvas.direction), (0, -1))
        self.book.bookmarks['art'].click()
        self.book.open_record('first-meeting')
        self.assertEqual((self.book.section, self.book.index, self.book.canvas.direction), ('growth', 0, -1))

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

    def test_recent_entry_opens_correct_spread_and_single_page(self):
        now = datetime.now() + timedelta(minutes=1)
        self.store.card('song:first','第一首','一起完整听完一次。',now)
        self.store.card('song:next','第二首','一起完整听完一次。',now+timedelta(seconds=1))
        self.book.reload()
        self.assertEqual([e.target for e in self.book.recent[:2]], ['song:next','song:first'])
        self.book.canvas.link_buttons[1].click()
        self.assertEqual(self.book.section, 'music')
        self.assertIn('song:first', [p.key for p in self.book.current_pages[self.book.index:self.book.index+2]])
        self.book.resize(530,650);self.app.processEvents()
        self.book.set_section('cover');self.book.turn(1)
        self.book.canvas.link_buttons[1].click()
        self.assertEqual(self.book.current_pages[self.book.index].key, 'song:first')

    def test_sources_open_only_on_click_and_do_not_count_as_memories(self):
        count = sum(self.book.record_counts.values())
        with patch('deskpet.mods.bond.album.QDesktopServices.openUrl',return_value=True) as open_url:
            self.book.set_section('art')
            active = [b for b in self.book.canvas.link_buttons if not b.isHidden()]
            self.assertEqual(len(active), 6)
            self.assertEqual(len({b.entry.target for b in active}), 6)
            open_url.assert_not_called()
            active[-1].click()
            self.assertEqual(open_url.call_args.args[0].toString(), active[-1].entry.target)
            self.assertEqual(sum(self.book.record_counts.values()), count)
            self.book.set_section('music')
            self.assertTrue(all(b.isHidden() for b in self.book.canvas.link_buttons))

    def test_a_single_pinned_record_survives_reopen_and_removal(self):
        old = datetime.now() - timedelta(days=5)
        for i in range(4):
            self.store.card(f'diary:{i}',f'留笺{i}','正文',old+timedelta(days=i))
        self.book.reload()
        self.book.open_record('diary:0')
        button = next(b for b in self.book.canvas.pin_buttons if b.key=='diary:0' and not b.isHidden())
        button.click()
        self.assertEqual(self.book.pinned,'diary:0')
        self.assertEqual(self.book.cover_links[0].target,'diary:0')
        self.assertEqual(len({entry.target for entry in self.book.cover_links}),3)
        other = MemoryBook(self.store)
        try:
            self.assertEqual(other.cover_links[0].target,'diary:0')
            other.toggle_pin('diary:1')
            self.book.reload()
            self.assertEqual(self.book.pinned,'diary:1')
            self.book.toggle_pin('diary:1')
            self.assertEqual(self.book.cover_links,self.book.recent)
            self.book.toggle_pin('diary:0')
            self.store.forget('diary:0');self.book.reload()
            self.assertEqual(self.book.cover_links,self.book.recent)
        finally:
            other.close()

    def test_listening_ticks_do_not_repaginate_closed_week(self):
        self.store.db.execute('UPDATE state SET affinity=150');self.store.refresh()
        with patch.object(self.store,'weekly',wraps=self.store.weekly) as weekly:
            self.book.reload()
            pages = self.book.pages
            with self.store.db:
                self.store.db.execute("INSERT INTO listening VALUES('2026-11-18','歌曲',60)")
            self.book.reload()
            self.assertIs(self.book.pages,pages)
            weekly.assert_not_called()
            self.book.set_section('week');self.book.reload()
            weekly.assert_called_once()

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
        with patch.object(self.book.canvas.art,'draw',return_value=False):
            self.book.set_section('growth');self.book.set_section('cover')
            self.book.canvas.animation.stop();self.book.canvas._finish()
            self.assertFalse(self.book.grab().isNull())


if __name__=='__main__':unittest.main()
