"""Real Qt passive teleport integration, isolated settings and synthetic art."""
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings, Qt, QRectF
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import Pet
from teleport_controller import TeleportController
from visual_style import APPEARANCE_REVISION


class NoStartup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
output = ROOT / 'preview/teleport'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='test-', dir=output) as directory:
    root = Path(directory)
    os.environ['LOCALAPPDATA'] = str(root)
    folder = root / 'characters/test'
    folder.mkdir(parents=True)
    image = QImage(100, 180, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setBrush(QColor('#55a6be'))
    p.drawEllipse(20, 5, 60, 65)
    p.drawRoundedRect(20, 60, 60, 115, 12, 12)
    p.end()
    image.save(str(folder / 'idle.png'))
    (folder / 'character.json').write_text(json.dumps(
        {'version': 1, 'id': 'teleport-test', 'name': 'Test', 'states': {'idle': 'idle.png'}}), encoding='utf-8')
    settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    settings.setValue('character_selection', 'external:test')
    settings.setValue('random_walk', False)
    pet = Pet(data_dir=root / 'data', settings=settings, startup=NoStartup(),
              characters_dir=root / 'characters')
    try:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.hide()
        pet.toolbar.hide()
        pet.bubble.hide()
        pet.show()
        app.processEvents()
        pet.dock_edge = ''
        bounds = pet.screen_bounds()
        pet.move(bounds.left()+30, bounds.top())
        pet.set_mode('listen')
        pet.grab()

        def ready():
            pet.stop_roaming()
            pet.panel.hide()
            pet.toolbar.hide()
            pet.bubble.hide()
            pet.click_timer.stop()
            pet.hold_timer.stop()
            pet.press_point = None
            pet.set_auto_teleport(True)
            pet.set_mode('listen')
            pet.last_interaction = time.monotonic()-20
            pet.teleport_controller = TeleportController(rng=random.Random(4))

        ready()
        # Actually enter via the scheduler, without waiting 45-120 real seconds.
        pet.teleport_controller._check_at = 0
        pet.tick_teleport(.033)
        assert pet.teleport_controller.active
        assert not pet.start_walk()  # Also works for a pack with no walking art.
        initial = pet.pos()
        positions = []
        for _ in range(70):
            previous = pet.pos()
            pet.tick_teleport(.033)
            pet.grab()
            if pet.pos() != previous:
                assert pet.teleport_controller.visual.person == 0
                assert pet.teleport_controller.visual.smoke == 0
                positions.append(pet.pos())
        assert len(positions) == 1 and pet.x() == initial.x() and pet.y() != initial.y()
        assert pet.behavior.mode == 'listen' and not pet.behavior.layers
        assert float(settings.value('teleport_cooldown_until')) > time.time()+590

        for elapsed in (.25, .82, 1.5):
            ready()
            assert pet._start_teleport()
            for _ in range(round(elapsed/.01)):
                pet.tick_teleport(.01)
            pet.open_tools(2)
            assert not pet.teleport_controller.active
            assert pet.teleport_controller.visual.person == 1
            assert not pet.behavior.layers

        ready()
        assert pet._start_teleport()
        assert pet.effects.isVisible() and pet.effects.teleporting
        pet.panel.effects_toggle.setChecked(False)
        pet.effects.sync()
        assert pet.effects.isVisible() and pet.effects.teleporting
        assert not pet.start_walk()
        pet.grab()
        QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=pet.hit_region.boundingRect().center())
        assert not pet.teleport_controller.active
        QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=pet.hit_region.boundingRect().center())
        ready()
        assert pet._start_teleport()
        pet.set_mode('sleep')
        assert not pet.teleport_controller.active and pet.behavior.mode == 'sleep'
        ready()
        assert pet._start_teleport()
        pet.playing = True
        pet.tick_teleport(.033)
        assert not pet.teleport_controller.active
        pet.playing = False
        ready()
        assert pet._start_teleport()
        pet.hide()
        assert not pet.teleport_controller.active
        pet.show()
        ready()
        assert pet._start_teleport()
        pet.set_auto_teleport(False)
        assert not pet.teleport_controller.active and not pet._start_teleport()
        ready()
        assert pet._start_teleport()
        pet.teleport_bounds = pet.teleport_bounds.adjusted(0, 1, 0, 0)
        pet.tick_teleport(.033)
        assert not pet.teleport_controller.active

        # Visual contact sheet with the real built-in static model, then render
        # Live2D too when local assets/runtime are available.
        pet.set_variant('refined')
        ready()
        pet.grab()
        assert pet._start_teleport()
        moments = (0, .30, .46, .70, .82, 1.18, 1.50, 1.85)
        cell = max(pet.width(), pet.effects.width()) + 12
        sheet = QImage(cell*4, (cell+30)*2, QImage.Format.Format_ARGB32)
        sheet.fill(QColor('#33434b'))
        painter = QPainter(sheet)
        for i, moment in enumerate(moments):
            pet.teleport_controller.elapsed = moment
            frame = pet.grab()
            x, y = i%4*cell, i//4*(cell+30)
            origin = pet.effects.pos()
            painter.drawPixmap(x+6+pet.x()-origin.x(), y+30+pet.y()-origin.y(), frame)
            painter.drawPixmap(x+6, y+30, pet.effects.grab())
            painter.setPen(QColor('white'))
            painter.drawText(x+12, y+20, f'{moment:.2f}s')
        painter.end()
        sheet.save(str(output / 'teleport-sequence.png'))
        pet.stop_teleport()
        if '--live2d' in sys.argv:
            assert pet.set_variant('live2d'), pet.panel.character_note.text()
            ready()
            pet.grab()
            assert pet._start_teleport()
            for moment in (0, .46, .82, 1.18, 1.85):
                pet.teleport_controller.elapsed = moment
                frame = pet.grab().toImage()
                assert not frame.isNull()
                frame.save(str(output / f'live2d-{moment:.2f}.png'))
                alpha_image = frame.convertToFormat(QImage.Format.Format_Alpha8)
                raw = bytes(alpha_image.constBits())
                stride = alpha_image.bytesPerLine()
                alpha = b''.join(raw[row*stride:row*stride+alpha_image.width()]
                                 for row in range(alpha_image.height()))
                if pet.teleport_controller.visual.person == 0:
                    assert max(alpha) == 0
                else:
                    assert max(alpha) > 0
                cloud = pet.effects.grab().toImage()
                cloud_alpha = cloud.convertToFormat(QImage.Format.Format_Alpha8)
                raw = bytes(cloud_alpha.constBits())
                stride = cloud_alpha.bytesPerLine()
                maximum = max(max(raw[row*stride:row*stride+cloud_alpha.width()])
                              for row in range(cloud_alpha.height()))
                assert (maximum == 0) == (pet.teleport_controller.visual.smoke == 0)
            pet.stop_teleport()
            assert pet.live2d_renderer is not None
            assert not pet.grab().isNull()
            print('PASS: native Live2D foreground cover, fully blank relocation, reveal and restore')
            if '--gif' in sys.argv:
                from render_teleport_gif import export
                export(pet, output)
        print('PASS: passive scheduler, ordered invisible relocation, persisted cooldown, PNG rendering, click/tool/mode/playback/hide/screen/disable interrupts')
    finally:
        pet.timer.stop()
        pet.fold_timer.stop()
        pet.click_timer.stop()
        pet.hold_timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.watchdog.stop()
        pet.panel.shutdown_audio()
        pet.close_live2d()
        pet.tray.hide()
        pet.hide()
        pet.panel.hide()
        pet.panel.store.close()
        pet.deleteLater()
        app.processEvents()
