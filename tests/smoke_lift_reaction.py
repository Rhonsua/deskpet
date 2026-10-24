"""Candidate Live2D + Qt integration; synthetic events, not real-input acceptance."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STAGE = ROOT/'experiments/live2d-tianyi/lift-model'
if not (STAGE/'action-map.json').exists():
    raise SystemExit('Candidate Cubism export is required for this local integration check.')

from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import live2d_renderer


class CandidateRenderer(live2d_renderer.Live2DRenderer):
    def __init__(self):
        super().__init__(STAGE)


live2d_renderer.Live2DRenderer = CandidateRenderer
from main import Pet
from visual_style import APPEARANCE_REVISION


class NoStartup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
output = ROOT/'preview/live2d/lift'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='integration-', dir=output) as temp:
    os.environ['LOCALAPPDATA'] = temp
    settings = QSettings(str(Path(temp)/'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'live2d')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=Path(temp)/'data', settings=settings, startup=NoStartup(),
              characters_dir=Path(temp)/'characters')
    try:
        assert pet.live2d_renderer is not None, pet.panel.character_note.text()
        assert {'ParamLiftArmL', 'ParamLiftArmR'} <= pet.live2d_renderer.parameter_ids
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.hide()
        pet.toolbar.hide()
        pet.dock_edge = ''
        pet.dock_reveal = pet.dock_target = 1
        pet.move(500, 200)
        pet.show()

        def draw():
            pet.update_live2d_geometry(pet.behavior.activity)
            pet.grab()
            return pet.live2d_renderer.lift_reaction.last_values

        def grab():
            draw()
            point = pet.hit_region.boundingRect().center()
            if not pet.hit_region.contains(point):
                bounds = pet.hit_region.boundingRect()
                point = next(QPoint(x, y)
                    for y in range(bounds.top(), bounds.bottom()+1)
                    for x in range(bounds.left(), bounds.right()+1)
                    if pet.hit_region.contains(QPoint(x, y)))
            # Use the real mouse handler and its explicit pickup entry point.
            QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=point)
            if pet.press_point is None:
                raise AssertionError('Synthetic pickup missed the painted character')
            pet.begin_drag()
            assert pet.dragging and pet.behavior.activity == 'lift'
            pet.behavior.tick(.2)
            return draw(), point

        for mode in ('idle', 'sleep', 'phone', 'sing'):
            pet.set_mode(mode)
            pet.behavior.tick(3)
            saved = pet.behavior.mode_elapsed
            values, point = grab()
            assert values['ParamEyeLOpen'] == 0
            assert 0 < values['ParamLiftArmL'] <= 1
            before = values['ParamLiftArmL']
            pet.behavior.tick(.1)
            assert abs(draw()['ParamLiftArmL']-before) > .01, 'held still must animate'
            assert pet.behavior.mode == mode and pet.behavior.mode_elapsed == saved
            QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=point)
            assert not pet.dragging and pet.behavior.activity == 'land'
            draw()
            pet.behavior.tick(.3)
            landed = draw()
            assert landed['ParamLiftArmL'] == landed['ParamLiftArmR'] == 0
            if mode == 'sleep':
                assert landed['ParamEyeLOpen'] == 0
            pet.behavior.tick(.4)
            restored = draw()
            assert pet.behavior.mode == mode and pet.behavior.activity == mode
            assert restored['ParamLiftArmL'] == restored['ParamLiftArmR'] == 0

        pet.set_mode('idle')
        grab()
        QApplication.sendEvent(pet, QEvent(QEvent.Type.UngrabMouse))
        assert not pet.dragging and not pet.behavior.dragging
        assert draw()['ParamLiftArmL'] == 0
        grab()
        pet.hide()
        assert not pet.dragging and pet.press_point is None
        pet.show()
        assert draw()['ParamLiftArmL'] == 0
        grab()
        assert pet.set_variant('refined')
        assert not pet.dragging and pet.behavior.mode == 'idle'
        pet.grab()
        print('PASS: candidate native renderer + synthetic Qt pickup/release; four saved modes, '
              'stationary arm animation, hidden/lost-grab/character-switch cleanup. '
              'Real desktop input is checked separately.')
    finally:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.tray.hide()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.hide()
        pet.panel.store.close()
        pet.close_live2d()
        pet.deleteLater()
        app.processEvents()
