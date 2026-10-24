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
        # Push past an edge while holding, pull back without releasing, then dock again.
        directions = {'left': QPoint(-1, 0), 'right': QPoint(1, 0),
                      'top': QPoint(0, -1), 'bottom': QPoint(0, 1)}
        for edge, outward in directions.items():
            pet.dock_edge = ''
            pet.move(bounds.center() - pet.rect().center())
            offset = QPoint(130, 90)
            pet.press_point = pet.pos() + offset
            pet.drag_offset = offset
            pet.begin_drag()
            edge_position = dock_position(pet.pos(), pet.size(), bounds, edge)
            pushed = edge_position + outward * 26 + offset
            pet.drag_to(pushed)
            pet.begin_drag()  # A delayed hold timeout must not detach the same gesture.
            assert pet.dragging and pet.drag_dock_edge == edge and pet.dock_target == 0
            pet.reveal_dock()
            assert pet.dock_target == 0, 'hover must not unfold a held push gesture'
            pet.drag_to(edge_position - outward * 48 + offset)
            assert pet.dragging and not pet.drag_dock_edge and not pet.dock_edge
            # Pull out, move back near the edge, then release: no magnet bounce.
            pet.drag_to(edge_position - outward * 12 + offset)
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=offset)
            assert not pet.dock_edge and settings.value('dock_edge') == ''
            pet.behavior.layers.clear()
            pet.press_point = pet.pos() + offset
            pet.drag_offset = offset
            pet.begin_drag()
            pet.drag_to(pushed)
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=offset)
            assert not pet.dragging and not pet.drag_dock_edge
            assert pet.dock_edge == edge and pet.dock_target == 0
            assert settings.value('dock_edge') == edge
        # Keep expanded while a tool is open, then fold after it closes.
        pet.reveal_dock()
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
        # A folded singer peeks calmly without changing music or saved intent.
        pet.set_mode('sing')
        pet.dock_edge, pet.dock_reveal = 'left', 0
        assert pet.display_activity() == 'idle' and pet.behavior.mode == 'sing'
        pet.grab()
        assert not pet.hit_region.isEmpty()
        for mode in ('sleep', 'phone'):
            pet.dock_edge = ''
            pet.set_mode(mode)
            pet.update_live2d_geometry(mode)
            pet.press_point = pet.pos() + QPoint(130, 90)
            pet.drag_offset = QPoint(130, 90)
            pet.begin_drag()
            pet.update_live2d_geometry('lift')
            pet.drag_to(dock_position(pet.pos(), pet.size(), bounds, 'left')
                        + QPoint(-26, 0) + pet.drag_offset)
            assert pet.drag_dock_edge == 'left'
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=QPoint(130, 90))
            assert pet.behavior.mode == mode and pet.display_activity() == mode
            assert pet.dock_target == 1, 'resting poses must remain fully visible'
        pet.set_mode('idle')
        pet.dock_edge = ''
        pet.update_live2d_geometry('idle')
        # Render different poses into the SAME image, then compare with a fresh buffer.
        # This catches retained pixels outside the next pose, including old particles.
        pet.phase = 40.8
        canvas = frame(pet)
        for action in ('happy', 'eat', 'lift', 'idle', 'land'):
            pet.behavior.layers.clear()
            if action == 'lift':
                pet.behavior.begin_drag()
            elif action != 'idle':
                pet.behavior.react(action, 2)
            pet.behavior.tick(0.3)
            pet.phase += 0.23
            canvas = frame(pet, canvas)
            assert canvas == frame(pet), 'retained pixels after ' + action
        pet.panel.show()
        pet.panel.tabs.setCurrentIndex(2)
        pet.panel.appearance.showPopup()
        app.processEvents()
        for combo in (pet.panel.appearance, pet.panel.mode_choice, pet.panel.playlist_choice,
                      pet.panel.output_choice):
            palette = combo.view().palette()
            assert palette.color(QPalette.ColorRole.Text).name() == '#000000'
            assert palette.color(QPalette.ColorRole.Base).name() == '#ffffff'
            assert palette.color(QPalette.ColorRole.HighlightedText).name() == '#000000'
            assert palette.color(QPalette.ColorRole.Highlight).name() == '#ffffff'
        pet.panel.appearance.view().grab().save(str(output / 'dropdown-dark-theme.png'))
        pet.panel.appearance.hidePopup()
        print('PASS: four-edge peek/reveal, held push/pull docking, scale, restore, detach, clean redraw and dark-theme dropdowns')
    finally:
        pet.timer.stop()
        pet.fold_timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.player.stop()
        pet.panel.player.setSource(QUrl())
        pet.panel.shutdown_audio()
        pet.tray.hide()
        pet.panel.store.close()
        pet.panel.hide()
        pet.hide()
