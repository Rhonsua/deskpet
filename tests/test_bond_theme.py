import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from types import SimpleNamespace
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication,QPushButton
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.widget import BondWidget

class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_dark_and_light_controls(self):
        original=self.app.palette()
        try:
            for color,dark in [('#17232a',True),('#f4f7fa',False)]:
                palette=QPalette(original);palette.setColor(QPalette.Window,QColor(color));self.app.setPalette(palette)
                store=BondStore(':memory:')
                mod=SimpleNamespace(store=store,active=True,analysis_owner=None,events=SimpleNamespace(summary=lambda:'',active=None),services=SimpleNamespace(),guess=lambda:None,weekly_show=lambda:None)
                w=BondWidget(mod);w.show();self.app.processEvents();self.assertEqual(w.dark,dark)
                w.tabs.setCurrentIndex(1);self.app.processEvents()
                advanced=next(x for x in w.findChildren(QPushButton) if x.text()=='高级设置');advanced.click()
                self.assertTrue(w.bpm.isVisible());self.assertTrue(w.auto_clip.isVisible())
                w.difficulty.showPopup();self.app.processEvents()
                view=w.difficulty.view();self.assertTrue(view.isVisible())
                bg=view.palette().color(QPalette.Base);fg=view.palette().color(QPalette.Text)
                self.assertGreater(abs(bg.lightness()-fg.lightness()),90)
                w.difficulty.hidePopup();w.tabs.setCurrentIndex(3);self.app.processEvents()
                self.assertFalse(w.nickname.isEnabled());self.assertTrue(w.theme.isVisible())
                w.close();store.db.close()
        finally:self.app.setPalette(original)

if __name__=='__main__': unittest.main()
