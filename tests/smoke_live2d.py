"""Real OpenGL/Qt frames and interaction-state smoke test; isolated user data."""
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from main import Pet
from pet_behavior import PetBehavior

app = QApplication([])


class NoStartup:
    supported = False
    def enabled(self):
        return False


output = Path(__file__).resolve().parents[1] / 'preview' / 'live2d'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='test-', dir=output) as temp:
    os.environ['LOCALAPPDATA'] = temp
    settings = QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat)
    pet = Pet(data_dir=Path(temp) / 'data', settings=settings, startup=NoStartup())
    try:
        assert pet.variant == 'live2d' and pet.live2d_renderer is not None, pet.panel.character_note.text()
        assert pet.panel.appearance.currentData() == 'live2d'
        pet.timer.stop()
        frames = {}
        times = []
        for activity, seconds in [('idle', 1), ('sing', .7), ('sleep', 3), ('phone', 3),
                                  ('eat', 1.4), ('lift', .5), ('land', .3), ('turn', 2)]:
            pet.behavior = PetBehavior()
            pet.behavior.set_mode(activity if activity in ('idle', 'sing', 'sleep', 'phone') else 'idle')
            if activity not in ('idle', 'sing', 'sleep', 'phone'):
                pet.behavior.react(activity, 10)
                pet.behavior.layers[-1].elapsed = seconds
            else:
                pet.behavior.mode_elapsed = seconds
            pet.update_live2d_geometry(activity)
            app.processEvents()
            start = time.perf_counter()
            frame = pet.grab().toImage()
            times.append(time.perf_counter() - start)
            assert not pet.hit_region.isEmpty(), activity
            assert frame.save(str(output / (activity + '.png')))
            frames[activity] = frame

        # A real Qt click hits the Live2D face and a held movement resumes sleeping.
        pet.set_mode('idle')
        pet.update_live2d_geometry('idle')
        pet.grab()
        QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=pet.head_region.boundingRect().center())
        assert pet.touch_head
        pet.click_timer.stop()
        pet.press_point = None
        pet.hold_timer.stop()
        # The held point stays attached to the pointer throughout the bounce.
        pet.press_point = pet.pos() + pet.head_region.boundingRect().center()
        pet.drag_offset = pet.press_point - pet.pos()
        pet.begin_drag()
        pet.behavior.layers[-1].elapsed = .1
        transform = pet.interaction_transform('lift')
        self_anchor = transform.map(pet.drag_anchor)
        assert (self_anchor - pet.drag_anchor).manhattanLength() < 1e-5
        assert not pet.grab().isNull() and not pet.hit_region.isEmpty()
        for seconds in (0, .1, .25, .6, 1.2):
            pet.behavior.layers[-1].elapsed = seconds
            assert pet.grab().save(str(output / f'pickup-{seconds}.png'))
        pet.dragging = False
        pet.press_point = None
        pet.behavior.end_drag(landing=False)
        pet.behavior = PetBehavior()
        pet.playing = True
        assert pet.behavior.activity == 'sing'
        pet.playing = False
        assert pet.behavior.activity == 'idle'
        pet.set_mode('listen')
        pet.playing = True
        assert pet.behavior.activity == 'idle'
        pet.playing = False
        pet.turn_body()
        assert pet.behavior.activity == 'turn'
        _, parts = pet.live2d_renderer.motions.sample('turn', 1)
        assert parts['ArmLMicSet'] == parts['ArmROpenSet'] == 1
        pet.behavior = PetBehavior()
        pet.set_mode('sleep')
        pet.behavior.tick(2)
        pet.behavior.begin_drag()
        pet.behavior.tick(1)
        pet.behavior.end_drag()
        pet.behavior.tick(.65)
        assert pet.behavior.activity == 'sleep'
        assert abs(pet.behavior.activity_elapsed - 2) < 1e-6, (pet.behavior.mode_elapsed, pet.behavior.layers)
        pet.update_live2d_geometry('sleep')
        pet.grab()
        assert pet.width() == 400
        for edge in ('left', 'right', 'top', 'bottom'):
            pet.set_mode('idle')
            pet.update_live2d_geometry('idle')
            pet.dock_edge, pet.dock_reveal = edge, 0
            pet.grab()
            assert not pet.hit_region.isEmpty(), edge
        pet.dock_edge = ''
        pet.set_mouse_passthrough(True)
        assert pet.windowFlags() & Qt.WindowType.WindowTransparentForInput
        pet.set_mouse_passthrough(False)
        pet.panel.appearance.setCurrentIndex(pet.panel.appearance.findData('refined'))
        assert pet.variant == 'refined' and pet.live2d_renderer is None
        from visual_style import preferred_variant
        reopened_settings = QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat)
        assert preferred_variant(reopened_settings) == 'refined', 'static selection must survive restart'
        assert pet.set_variant('live2d'), pet.panel.character_note.text()
        renderer = pet.live2d_renderer
        iris_index = renderer.model.GetDrawableIds().index('Irises')
        renderer.pointer = (-1, 0, 1)
        renderer.frame('idle', 0).save(str(output / 'pointer-left.png'))
        left_eye = renderer.model.GetDrawableVertices(iris_index)
        renderer.pointer = (1, 0, 1)
        renderer.frame('idle', 0).save(str(output / 'pointer-right.png'))
        right_eye = renderer.model.GetDrawableVertices(iris_index)
        assert left_eye != right_eye, 'nearby pointer must drive the native model'
        a = renderer.frame('sleep', 0)
        renderer.pointer = (-1, 0, 1)
        b = renderer.frame('sleep', 0)
        assert a == b, 'resting pose must ignore pointer tracking'
        renderer.pointer = (0, 0, 0)
        from music_beats import BeatSample
        left_beat = BeatSample(0, .5, True, 120)
        right_beat = BeatSample(1, .5, True, 120)
        left_frame = renderer.frame('sing', .7, left_beat)
        right_frame = renderer.frame('sing', .7, right_beat)
        assert not left_frame.isNull() and left_frame != right_frame, 'actual beats must move the rendered feet'
        assert renderer.frame('sleep', 0, left_beat) == renderer.frame('sleep', 0, right_beat), 'sleep must ignore beats'
        # Side-by-side, identical logical pixel scale and aligned ground line.
        comparison = QImage(660, 340, QImage.Format.Format_ARGB32)
        comparison.fill(QColor('#26303d'))
        p = QPainter(comparison)
        p.drawImage(0, 20, frames['idle'])
        p.drawImage(260, 20, frames['sleep'])
        p.end()
        comparison.save(str(output / 'standing-sleep-scale.png'))
        print('PASS: native frames, poses, hit testing, state resume, four dock edges, passthrough and renderer reload')
        print('Frame render milliseconds:', [round(value * 1000, 1) for value in times])
    finally:
        pet.timer.stop()
        pet.fold_timer.stop()
        pet.hold_timer.stop()
        pet.click_timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.watchdog.stop()
        pet.close_live2d()
        pet.panel.shutdown_audio()
        pet.tray.hide()
        pet.toolbar.hide()
        pet.bubble.hide()
        pet.panel.hide()
        pet.panel.store.close()
        pet.hide()
        pet.deleteLater()
        app.processEvents()
