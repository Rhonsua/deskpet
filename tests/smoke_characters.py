"""Real Qt switching, rendering, hot reload, persistence and missing-pack recovery."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import Pet


app = QApplication([])


class NoStartup:
    supported = False
    def enabled(self):
        return False


def dispose(pet):
    pet.timer.stop()
    pet.fold_timer.stop()
    pet.click_timer.stop()
    pet.hold_timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.bilibili.watchdog.stop()
    pet.panel.shutdown_audio()
    pet.tray.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    pet.panel.hide()
    pet.panel.store.close()
    pet.hide()
    pet.deleteLater()
    app.processEvents()


def draw(path, color):
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(50, 20, 150, 130)
    painter.drawRoundedRect(70, 130, 115, 110, 15, 15)
    painter.end()
    assert image.save(str(path))


with tempfile.TemporaryDirectory(prefix='tianyi-character-') as scratch:
    root = Path(scratch)
    os.environ['LOCALAPPDATA'] = scratch
    packs = root / 'characters'
    folder = packs / '我的角色'
    folder.mkdir(parents=True)
    draw(folder / 'idle.png', '#4e83bb')
    settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
    def create():
        return Pet(data_dir=root / 'data', startup=NoStartup(), settings=settings, characters_dir=packs)
    pet = create()
    try:
        assert pet.panel.appearance.count() == 2, 'do not scan unselected packs at startup'
        pet.refresh_characters()
        selection = 'external:我的角色'
        index = pet.panel.appearance.findData(selection)
        assert index >= 0
        pet.set_mode('sleep')
        pet.panel.appearance.setCurrentIndex(index)
        app.processEvents()
        assert pet.variant == selection and pet.character_name == '我的角色'
        assert pet.sleeping and not pet.singing_rigs
        assert pet.frames['sleep'].cacheKey() == pet.frames['idle'].cacheKey()
        assert pet.sprite.size().width() == 256, 'preserve full canvas'
        assert not pet.grab().isNull() and not pet.hit_region.isEmpty()
        level, notes = pet.panel.store.pet()['level'], pet.panel.store.pet()['notes']

        # A real click on the custom head uses its anchor rather than Tianyi's cutoff.
        pet.set_mode('idle')
        app.processEvents()
        pet.grab()
        QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=pet.head_region.boundingRect().center())
        assert pet.touch_head
        pet.click_timer.stop()
        pet.press_point = None
        pet.hold_timer.stop()

        draw(folder / 'sing-front.png', '#64a848')
        manifest = {'version': 1, 'id': 'custom', 'name': '新名字',
                    'states': {'idle': 'idle.png', 'sing-front': 'sing-front.png'},
                    'anchors': {'head': [.48, .30], 'feet': [.48, .94]}}
        (folder / 'character.json').write_text(json.dumps(manifest), encoding='utf-8-sig')
        old_key = pet.sprite.cacheKey()
        draw(folder / 'idle.png', '#e1aa48')
        pet.refresh_characters(reload_current=True)
        assert pet.sprite.cacheKey() != old_key and pet.character_name == '新名字'
        assert pet.frames['sing-left'].cacheKey() == pet.frames['sing-front'].cacheKey()
        assert pet.frames['sing-right'].cacheKey() == pet.frames['sing-front'].cacheKey()
        assert pet.panel.store.pet()['level'] == level and pet.panel.store.pet()['notes'] == notes
        for mode in ('sing', 'sleep', 'phone', 'idle'):
            pet.set_mode(mode)
            app.processEvents()
            pet.grab()
            assert not pet.hit_region.isEmpty(), mode
        for edge in ('left', 'right', 'top', 'bottom'):
            pet.dock_edge, pet.dock_reveal = edge, 0
            app.processEvents()
            pet.grab()
            assert not pet.hit_region.isEmpty(), edge
        pet.dock_edge = ''
        pet.dock_reveal = 1

        # Invalid refresh keeps the last good images and selection.
        valid_key = pet.sprite.cacheKey()
        (folder / 'idle.png').write_bytes(b'broken')
        pet.refresh_characters(reload_current=True)
        assert pet.sprite.cacheKey() == valid_key and pet.variant == selection
        assert '失败' in pet.panel.character_note.text()
        draw(folder / 'idle.png', '#e1aa48')
        assert pet.set_variant(selection)
        pet.set_mode('sleep')
        pet.behavior.begin_drag()
        pet.behavior.end_drag(landing=False)
        assert pet.sleeping, 'switching must preserve activity/temporary-state rules'
        pet.set_variant('simple')
        assert pet.character_pack is None and pet.variant == 'refined'
        assert pet.set_variant(selection)
    finally:
        dispose(pet)

    pet = create()
    try:
        assert pet.variant == selection and pet.character_name == '新名字'
        assert pet.sleeping
    finally:
        dispose(pet)
    shutil.rmtree(folder)
    pet = create()
    try:
        assert pet.variant == 'refined' and pet.character_pack is None
        assert '已恢复内置' in pet.panel.character_note.text()
    finally:
        dispose(pet)
print('PASS: PNG-only packs, settings selection, anchors, full canvas, fallbacks, hot reload, persistence and safe recovery')
