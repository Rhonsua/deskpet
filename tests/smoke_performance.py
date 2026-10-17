"""Check durable-mode restore and independent leg motion with actual Qt rendering."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from main import Pet


class NoStartup:
    supported = False
    def enabled(self):
        return False


def dispose(pet):
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.audio_router.poll.stop()
    pet.tray.hide()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()


app = QApplication([])
with tempfile.TemporaryDirectory() as scratch:
    settings = QSettings(str(Path(scratch) / 'mode.ini'), QSettings.Format.IniFormat)
    first = Pet(data_dir=Path(scratch) / 'one', startup=NoStartup(), settings=settings)
    first.timer.stop()
    first.panel.progress_timer.stop()
    try:
        for mode in ('sleep', 'phone', 'sing', 'idle', 'listen'):
            first.set_mode(mode)
            first.press_point = first.pos() + QPoint(130, 90)
            first.drag_offset = QPoint(130, 90)
            first.begin_drag()
            first.behavior.tick(15)
            first.dragging = False
            first.behavior.end_drag()
            first.behavior.tick(0.7)
            assert first.behavior.mode == mode
        first.set_mode('phone')
        settings.sync()
        second = Pet(data_dir=Path(scratch) / 'two', startup=NoStartup(), settings=settings)
        try:
            assert second.behavior.mode == 'phone'
            assert not second.behavior.layers, 'transient actions must not be persisted'
        finally:
            dispose(second)
        rig = first.singing_rigs['sing-front']
        def legs_at(moment):
            image = QImage(rig.pixmap.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            mask = rig.draw(painter, moment, 1.0)
            painter.end()
            assert not mask.isEmpty()
            return image
        a, b = legs_at(0), legs_at(0.3)
        assert a.copy(0, 0, a.width(), rig.hem) == b.copy(0, 0, b.width(), rig.hem)
        assert a != b, 'legs should move independently below the stationary upper body'
        first.set_mode('sing')
        app.processEvents()
        started = time.perf_counter()
        for index in range(90):
            first.phase = index / 30
            image = first.grab().toImage()
            assert image.pixelColor(0, 0).alpha() == 0
        duration = time.perf_counter() - started
        print(f'PASS: mode restore, temporary overlays, independent leg movement; render {90 / duration:.1f} fps')
    finally:
        dispose(first)
