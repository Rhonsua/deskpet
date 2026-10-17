"""Isolated docking, transparent redraw and dark-palette popup regression checks."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'windows' if '--native' in sys.argv else 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from edge_docking import EDGES, dock_position
from main import Pet


class NoStartup:
    supported = False
    def enabled(self):
        return False


def frame(pet, canvas=None):
    if canvas is None:
        canvas = QImage(pet.size(), QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    pet.render(painter, QPoint(), pet.rect())
    painter.end()
    return canvas


app = QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families = QFontDatabase.applicationFontFamilies(font_id)
app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
# Exercise the system-dark-theme mismatch that originally made popup rows illegible.
palette = app.palette()
for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base):
    palette.setColor(role, QColor('#171717'))
for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text):
    palette.setColor(role, QColor('#EEEEEE'))
app.setPalette(palette)
output = Path(__file__).resolve().parents[1] / 'preview'
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as scratch:
    settings = QSettings(str(Path(scratch) / 'settings.ini'), QSettings.Format.IniFormat)
    pet = Pet(data_dir=Path(scratch) / 'data', startup=NoStartup(), settings=settings)
    try:
        app.processEvents()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        bounds = pet.screen_bounds()
        pet.underMouse = lambda: False  # Deterministic pointer location on offscreen platform.
        for edge in EDGES:
            pet.move(dock_position(bounds.center() - pet.rect().center(), pet.size(), bounds, edge))
            pet.snap_to_edge()
            assert pet.dock_edge == edge
            pet.fold_dock()
            assert pet.dock_target == 0
            for _ in range(12):
                pet.last_frame_time = time.monotonic() - 0.033
                pet.animate()
            assert pet.dock_reveal == 0
            app.processEvents()
            peek = pet.grab().toImage()
            assert not pet.hit_region.isEmpty()
            opaque_rows = sum(any(peek.pixelColor(x, y).alpha() > 180 for x in range(peek.width()))
                              for y in range(peek.height()))
            assert opaque_rows > 30, (edge, opaque_rows)
            assert peek.save(str(output / ('edge-' + edge + '.png')))
            pet.set_scale(1.25)
            assert pet.pos() == dock_position(pet.pos(), pet.size(), bounds, edge)
            pet.set_scale(1.0)
            pet.reveal_dock()
            for _ in range(12):
                pet.last_frame_time = time.monotonic() - 0.033
                pet.animate()
            assert pet.dock_reveal == 1
        # Keep expanded while a tool is open, then fold after it closes.
        pet.panel.show()
        pet.fold_dock()
        assert pet.dock_target == 1
        pet.panel.hide()
        pet.fold_dock()
        assert pet.dock_target == 0
        # The stored edge is restored and a long press can detach it.
        pet.restore()
        assert pet.dock_edge == 'bottom' and pet.dock_reveal == 0
        pet.press_point = pet.pos() + QPoint(pet.width() // 2, pet.height() - 50)
        pet.begin_drag()
        assert pet.dragging and pet.dock_edge == '' and pet.dock_reveal == 1
        pet.move(bounds.center() - pet.rect().center())
        QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=QPoint(130, 90))
        assert not pet.dragging and pet.dock_edge == ''
        assert settings.value('dock_edge') == ''
        # Render different poses into the SAME image, then compare with a fresh buffer.
        # This catches retained pixels outside the next pose, including old particles.
        pet.phase = 40.8
        canvas = frame(pet)
        for action in ('happy', 'eat', 'lift', 'idle', 'land'):
            pet.action = action
            pet.action_start = 40.5
            pet.phase += 0.23
            canvas = frame(pet, canvas)
            assert canvas == frame(pet), 'retained pixels after ' + action
        pet.panel.show()
        pet.panel.tabs.setCurrentIndex(2)
        pet.panel.appearance.showPopup()
        app.processEvents()
        for combo in (pet.panel.appearance, pet.panel.mode_choice, pet.panel.playlist_choice):
            palette = combo.view().palette()
            assert palette.color(QPalette.ColorRole.Text).name() == '#263e4d'
            assert palette.color(QPalette.ColorRole.Base).name() == '#ffffff'
            assert palette.color(QPalette.ColorRole.HighlightedText).name() == '#ffffff'
        pet.panel.appearance.view().grab().save(str(output / 'dropdown-dark-theme.png'))
        pet.panel.appearance.hidePopup()
        print('PASS: four-edge peek/reveal, scale, restore, detach, clean redraw and dark-theme dropdowns')
    finally:
        pet.timer.stop()
        pet.fold_timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.player.stop()
        pet.panel.player.setSource(QUrl())
        pet.tray.hide()
        pet.panel.store.close()
        pet.panel.hide()
        pet.hide()
