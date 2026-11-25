"""Real shop controls, animation previews and their relationship to the pet wallet."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from deskpet.pet.catalog import CATEGORIES, ITEMS
from deskpet.pet.store import PetStore
from deskpet.ui.shop import PetShop
from deskpet.ui.shop_art import SCENE_FPS, SCENE_LOOP_SECONDS, item_pixmap, scene_frame


class PetShopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = QWidget()
        self.panel.store = PetStore(':memory:')
        self.panel.buy_shop_item = self.panel.store.buy_item
        self.shop = PetShop(self.panel)
        self.shop.show()
        self.app.processEvents()

    def tearDown(self):
        self.shop.close()
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.panel.store.close()

    def test_categories_and_preview_do_not_spend_notes(self):
        for category in CATEGORIES:
            self.shop.tab_buttons[category].click()
            self.assertTrue(any(card.isVisible() and card.item.category == category for card in self.shop.cards.values()))
        self.shop.dynamic_button.click()
        animated = [card for card in self.shop.cards.values() if card.isVisible()]
        self.assertEqual(len(animated), 3)
        self.app.processEvents()
        for card in animated:
            self.assertTrue(card.item.animated)
            self.assertFalse(card.button.isEnabled())
            self.assertFalse(item_pixmap(card.item.key).isNull())
            self.assertLess(card.geometry().right(), self.shop.scroll.viewport().width())
        self.shop.preview_scene(ITEMS['encore'])
        self.app.processEvents()
        self.assertTrue(self.shop.preview.timer.isActive())
        self.assertEqual(self.panel.store.pet()['notes'], 20)
        self.shop.hide()
        self.assertFalse(self.shop.preview.timer.isActive())

    def test_equip_remove_and_narrow_layout(self):
        self.shop.tab_buttons['background'].click()
        self.shop.cards['picnic'].button.click()
        self.assertEqual(self.panel.store.shop_settings()['background'], '')
        self.shop.cards['picnic'].button.click()
        self.assertEqual(self.panel.store.shop_settings()['background'], 'picnic')
        self.shop.resize(365, 570)
        self.app.processEvents()
        self.assertEqual(self.shop.columns, 1)
        self.shop.tab_buttons['food'].click()
        self.shop.cards['bao'].button.click()
        self.assertEqual(self.panel.store.pet()['notes'], 12)

    def test_full_scenes_change_across_frames_and_cost_more(self):
        static_price = max(i.price for i in ITEMS.values()
                           if i.category == 'background' and not i.animated and not i.panoramic)
        for item in ITEMS.values():
            self.assertFalse(item_pixmap(item.key).isNull(), item.key)
            if not item.animated:
                continue
            self.assertGreater(item.price, static_price)
            start = scene_frame(item.key, 200, 240, 0).toImage()
            later = scene_frame(item.key, 200, 240, 3 * SCENE_FPS).toImage()
            self.assertEqual(start.pixelColor(100, 5).alpha(), 255)
            self.assertEqual(start.pixelColor(100, 225).alpha(), 255)
            self.assertNotEqual(start, later)

    def test_panorama_can_be_explored_before_buying_and_re_equipped_for_free(self):
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        item = ITEMS['musicbox-town']
        self.assertGreater(item.price, max(i.price for i in ITEMS.values() if i.key != item.key))
        self.shop.tab_buttons['background'].click()
        self.shop.panorama_button.click()
        selected = [card for card in self.shop.cards.values() if card.isVisible()]
        self.assertEqual([card.item for card in selected], [item])
        card = selected[0]
        self.assertFalse(card.button.isEnabled())
        card.findChild(QToolButton).click()
        preview = self.shop.preview
        self.assertTrue(preview.isVisible())
        self.assertFalse(preview.timer.isActive())
        first = preview.grab().toImage()
        point = QPoint(90, 160)
        move = QMouseEvent(QEvent.MouseMove, QPointF(point), QPointF(preview.mapToGlobal(point)),
                           Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(preview, move)
        self.assertNotEqual(first, preview.grab().toImage())
        self.assertEqual(self.panel.store.pet()['notes'], 20)
        preview.close()
        with self.panel.store.db:
            self.panel.store.db.execute('UPDATE pet SET notes=?', (item.price,))
        self.shop.refresh(self.panel.store.pet())
        for expected in (item.key, '', item.key):
            card.button.click()
            self.assertEqual(self.panel.store.shop_settings()['background'], expected)
            self.assertEqual(self.panel.store.pet()['notes'], 0)

    def test_static_background_uses_no_animation_frames(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QPainter, QPixmap
        from deskpet.ui.shop_art import draw_background
        pixmap = QPixmap(200, 310)
        painter = QPainter(pixmap)
        try:
            with patch('deskpet.ui.shop_art.scene_frame') as animated:
                draw_background(painter, 'picnic', QSize(200,310), 1, 0)
                draw_background(painter, '', QSize(200,310), 1, 1)
                animated.assert_not_called()
        finally:
            painter.end()

    def test_anchors_and_loop_on_every_scene(self):
        from PySide6.QtCore import QRect
        duration = SCENE_FPS * SCENE_LOOP_SECONDS
        for key in ('cloudsky', 'fireflies', 'encore'):
            with self.subTest(key=key):
                def frame(n):
                    return scene_frame(key, 220, 270, n).toImage()
                first = frame(0)
                floor = QRect(6, 257, 208, 7)
                for n in (1, duration//5, duration//2, duration-1):
                    self.assertEqual(first.copy(floor), frame(n).copy(floor))
                self.assertNotEqual(first, frame(duration//3))
                self.assertEqual(first, frame(duration))
                self.assertEqual(frame(1), frame(duration + 1))

    def test_earnings_are_visible_and_track_progress_without_a_purchase(self):
        self.shop.earn.click()
        self.assertTrue(self.shop.note_guide.isVisible())
        self.assertIn('+6', self.shop.earning_status['chat'].text())
        self.panel.store.award_daily_notes('chat')
        self.shop.refresh(self.panel.store.pet())
        self.assertIn('已得 6', self.shop.earning_status['chat'].text())
        for _ in range(12):
            self.panel.store.tick_running(5)
        self.shop.refresh(self.panel.store.pet())
        self.assertIn('1/30', self.shop.earning_status['company'].text())
        self.assertIn('26', self.shop.wallet.text())
