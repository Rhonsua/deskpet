import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from deskpet.mods.bond.store import BondStore, CATEGORIES
from deskpet.mods.bond.widget import BondWidget

class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.store=BondStore(':memory:')
        self.events=SimpleNamespace(summary=lambda:'',active=None,defer=Mock(return_value=True))
        self.present=Mock(return_value=True)
        self.mod=SimpleNamespace(store=self.store,active=True,analysis_owner=None,events=self.events,services=SimpleNamespace(present=self.present),guess=lambda:None,weekly_show=lambda:None)
        self.widget=BondWidget(self.mod)

    def tearDown(self):
        self.widget.close();self.store.db.close()

    def test_host_entry_and_fallback(self):
        self.widget.present_host('food');self.present.assert_called_once_with('food')
        self.present.return_value=False;self.widget.present_host('chat')
        self.assertIn('原控制面板',self.widget.note.text())
        del self.mod.services.present;self.widget.present_host('control')
        self.assertIn('原控制面板',self.widget.note.text())

    def test_defer_and_daily_states(self):
        self.events.active={'kind':'headpat'};self.widget.refresh()
        self.assertFalse(self.widget.defer_need.isHidden())
        self.widget.defer_wish(True);self.events.defer.assert_called_once_with(today=True)
        self.assertIn('0 / 5',self.widget.daily_title.text())
        for key in CATEGORIES:self.store.award(key)
        self.widget.refresh();self.assertIn('5 / 5',self.widget.daily_title.text())
        self.assertIn('安心休息',self.widget.recommendation.text())
        self.assertTrue(all('已记录' in item.text() for item in self.widget.category_status.values()))

    def test_tab_order(self):
        self.assertEqual([self.widget.tabs.tabText(i) for i in range(4)],['今天的陪伴','节奏演出','成长纪念集','舞台与纪念'])

    def test_book_is_the_only_page_content_and_back_restores_dashboard(self):
        self.widget.resize(980,800);self.widget.show();self.app.processEvents()
        self.widget.tabs.setCurrentIndex(2);self.app.processEvents()
        self.assertTrue(self.widget.album.isVisible())
        self.assertFalse(self.widget.hero.isVisible())
        self.assertFalse(self.widget.note.isVisible())
        self.assertFalse(self.widget.tabs.tabBar().isVisible())
        self.widget.album.bookmarks['growth'].click()
        self.assertEqual(self.widget.album.section,'growth')
        self.widget.album.back.click();self.app.processEvents()
        self.assertEqual(self.widget.tabs.currentIndex(),0)
        self.assertTrue(self.widget.hero.isVisible())
        self.assertTrue(self.widget.tabs.tabBar().isVisible())
        self.widget.hide();self.assertFalse(self.widget.refresh_timer.isActive())
        self.widget.show();self.assertTrue(self.widget.refresh_timer.isActive())

if __name__=='__main__':unittest.main()
