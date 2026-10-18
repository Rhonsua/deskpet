"""Edge hover/press/drag and click-through recovery using disposable settings.

Use --native to additionally inspect the actual Windows input-transparent style.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'windows' if '--native' in sys.argv else 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QEnterEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from edge_docking import dock_position
from main import Pet


class NoStartup:
    supported = False
    def enabled(self):
        return False


def dispose(pet):
    pet.timer.stop()
    pet.fold_timer.stop()
    pet.hold_timer.stop()
    pet.click_timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.bilibili.watchdog.stop()
    if pet.panel._audio_router is not None:
        pet.panel._audio_router.poll.stop()
    pet.tray.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()


def native_transparent(pet):
    import ctypes
    from ctypes import wintypes
    getter = ctypes.windll.user32.GetWindowLongPtrW
    getter.argtypes = [wintypes.HWND, ctypes.c_int]
    getter.restype = ctypes.c_ssize_t
    return bool(getter(int(pet.winId()), -20) & 0x20)  # GWL_EXSTYLE, WS_EX_TRANSPARENT


app = QApplication([])
with tempfile.TemporaryDirectory(prefix='tianyi-input-') as scratch:
    settings = QSettings(str(Path(scratch) / 'input.ini'), QSettings.Format.IniFormat)
    pet = Pet(data_dir=Path(scratch) / 'data', startup=NoStartup(), settings=settings)
    try:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        app.processEvents()
        pet.underMouse = lambda: True
        bounds = pet.screen_bounds()
        for edge, inward in (('left', QPoint(120, 0)), ('right', QPoint(-120, 0)),
                              ('top', QPoint(0, 120)), ('bottom', QPoint(0, -120))):
            pet.behavior.layers.clear()
            pet.move(dock_position(bounds.center() - pet.rect().center(), pet.size(), bounds, edge))
            pet.snap_to_edge()
            pet.fold_dock()
            assert pet.dock_target == 0, 'hover must not prevent folding'
            for _ in range(12):
                pet.last_frame_time = time.monotonic() - .033
                pet.animate()
            pet.grab()
            region = pet.hit_region.boundingRect()
            hit = next(QPoint(x, y) for y in range(region.top(), region.bottom()+1)
                       for x in range(region.left(), region.right()+1)
                       if pet.hit_region.contains(QPoint(x, y)))
            app.sendEvent(pet, QEnterEvent(QPointF(hit), QPointF(hit), QPointF(pet.mapToGlobal(hit))))
            assert pet.dock_target == 0, 'enter must not reveal the pet'
            QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=hit)
            QTest.qWait(330)
            assert not pet.dragging and pet.dock_edge == edge and pet.dock_target == 0
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=hit)
            QTest.qWait(240)
            assert pet.dock_target == 0, 'click or stationary hold must not reveal the pet'
            QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=hit)
            point = pet.mapToGlobal(hit) + inward
            event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(hit + inward), QPointF(point),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            app.sendEvent(pet, event)
            assert pet.dragging and not pet.dock_edge and pet.dock_reveal == 1
            pet.move(bounds.center() - pet.rect().center())
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=QPoint(130, 90))
            assert not pet.dragging and not pet.dock_edge

        # Settings and tray must remain usable when the character takes no input.
        pet.set_mode('sleep')
        position = pet.pos()
        pet.panel.passthrough_toggle.setChecked(True)
        app.processEvents()
        flag = Qt.WindowType.WindowTransparentForInput
        assert pet.mouse_passthrough and pet.windowFlags() & flag
        assert pet.passthrough_action.isChecked() and pet.isVisible() and pet.pos() == position
        assert not pet.panel.windowFlags() & flag and not pet.toolbar.windowFlags() & flag
        if '--native' in sys.argv:
            assert native_transparent(pet), 'native Windows pass-through style was not applied'
        settings.sync()
        second = Pet(data_dir=Path(scratch) / 'data2', startup=NoStartup(), settings=settings)
        try:
            assert second.mouse_passthrough and second.windowFlags() & flag
            second.passthrough_action.setChecked(False)
            assert not second.mouse_passthrough and not second.panel.passthrough_toggle.isChecked()
        finally:
            dispose(second)
        recovery = next(action for action in pet.tray.contextMenu().actions()
                        if action.text() == '关闭鼠标穿透并找回天依')
        recovery.trigger()
        app.processEvents()
        assert not pet.mouse_passthrough and not pet.windowFlags() & flag
        assert not pet.panel.passthrough_toggle.isChecked() and pet.isVisible()
        assert pet.behavior.mode == 'sleep', 'input changes must preserve the activity'
        if '--native' in sys.argv:
            assert not native_transparent(pet)
        assert pet.panel._audio is None, 'input settings must not start local audio'
        print('PASS: four-edge hover/click/hold stays folded, drag detaches; input pass-through, settings, restart and tray recovery')
    finally:
        dispose(pet)
