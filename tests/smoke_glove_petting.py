"""Synthetic input integration with real Live2D/Qt rendering.

This deliberately replaces pointer/occlusion readings; it does NOT verify real
desktop mouse input, Windows occlusion, or the visual glove under the pointer.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import Pet
from visual_style import APPEARANCE_REVISION


class NoStartup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
output = Path(__file__).resolve().parents[1] / 'preview' / 'glove-petting'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='test-', dir=output) as temp:
    os.environ['LOCALAPPDATA'] = temp
    settings = QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'live2d')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=Path(temp) / 'data', settings=settings, startup=NoStartup())
    try:
        assert pet.live2d_renderer is not None, pet.panel.character_note.text()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.hide()
        pet.dock_edge = ''
        pet.set_mode('sing')
        pet.behavior.tick(4)
        saved_time = pet.behavior.mode_elapsed
        pet.update_live2d_geometry('sing')
        pet.grab()
        before = pet.panel.store.pet()['mood']
        pet.pat()
        pet.bubble.hide()
        assert pet.petting and pet.cursor().shape() == Qt.CursorShape.BitmapCursor
        assert pet.behavior.activity == 'sing' and pet.panel.store.pet()['mood'] == before
        # Explicit mode also works when passive mouse interactions are disabled.
        pet.panel.interactions_toggle.setChecked(False)
        center = pet.head_region.boundingRect().center()
        QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(pet, center + QPoint(25, 0))
        pet.begin_drag()
        QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=center)
        assert not pet.dragging and not pet.hold_timer.isActive() and not pet.click_timer.isActive()
        assert pet.petting

        def stroke(point, visible=True):
            pet.last_frame_time = time.monotonic() - .1
            with patch('desktop_pet.QCursor.pos', return_value=pet.mapToGlobal(point)), \
                    patch.object(pet, 'pointer_reaches_pet', return_value=visible):
                pet.animate()

        for i in range(20):
            stroke(center + QPoint(15 if i % 2 else -15, 0), visible=False)
        assert pet.behavior.activity == 'sing', 'occluded character must not react'
        for i in range(20):
            stroke(QPoint(0, 0))
        assert pet.behavior.activity == 'sing', 'outside the head must not react'
        resumed_time = pet.behavior.mode_elapsed
        for i in range(2):
            stroke(center)
        assert pet.active_petting.strength > .3, 'contact must respond immediately'
        assert pet.glove_overlay_alpha > .8 and pet.glove_contact
        assert pet.cursor().shape() == Qt.CursorShape.BlankCursor, 'foreground hand must replace the small cursor on contact'
        assert pet.panel.store.pet()['mood'] == before, 'contact alone gives no reward'
        for i in range(60):
            stroke(center + QPoint(round(15*__import__('math').sin(i*.3)), 0))
        assert pet.active_petting.phase == 'stroking', 'slow synthetic strokes sustain feedback'
        assert pet.active_petting.strength > .6
        assert pet.behavior.activity == 'sing', 'continuous feedback must not overwrite the saved activity'
        assert pet.panel.store.pet()['mood'] == before + 2
        pet.reward_pat()
        assert pet.panel.store.pet()['mood'] == before + 2, 'reward cooldown must survive mode entry'
        clock_at_rub = pet.behavior.mode_elapsed
        assert clock_at_rub >= resumed_time >= saved_time
        assert pet.grab().save(str(output / 'head-rub.png'))
        for i in range(20):
            stroke(center + QPoint(15 if i % 2 else -15, 0))
        assert pet.active_petting.strength > .6, 'feedback must continue during reward cooldown'
        assert pet.panel.store.pet()['mood'] == before + 2
        assert pet.behavior.activity == 'sing'
        assert abs(pet.behavior.mode_elapsed - clock_at_rub) < 1e-6
        # Right click exits without opening another menu.
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, center, pet.mapToGlobal(center))
        QApplication.sendEvent(pet, event)
        assert not pet.petting and not pet.toolbar.isVisible()
        assert pet.glove_overlay_alpha == 0 and not pet.glove_contact
        assert pet.cursor().shape() != Qt.CursorShape.BlankCursor
        for _ in range(8):
            stroke(center)
        assert pet.active_petting.strength < .01
        assert pet.behavior.mode_elapsed > clock_at_rub, 'original activity clock resumes after release'
        pet.pat()
        QApplication.sendEvent(pet, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        assert not pet.petting
        pet.pat()
        pet.set_mode('sleep')
        pet.pat()
        assert not pet.petting and pet.behavior.mode == 'sleep'
        pet.set_mode('idle')
        pet.pat()
        pet.set_mouse_passthrough(True)
        assert not pet.petting
        pet.set_mouse_passthrough(False)
        pet.pat()
        pet.hide()
        assert not pet.petting
        pet.show()
        pet.pat()
        assert pet.set_variant('refined')
        assert not pet.petting
        pet.pat()
        assert pet.behavior.activity == 'happy', 'static characters retain their original pat'
        print('PASS: synthetic-input Live2D integration, continuous feedback, reward cooldown, state resume and exits; real input/occlusion NOT tested')
    finally:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.panel.store.close()
        pet.tray.hide()
        pet.hide()
        pet.close_live2d()
        pet.deleteLater()
        app.processEvents()
