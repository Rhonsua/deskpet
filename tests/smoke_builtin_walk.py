"""Render the local Tianyi walking art in the actual desktop window."""
import os
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication
from main import Pet
from visual_style import APPEARANCE_REVISION


class NoStartup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
output = ROOT / 'preview/walk-runtime'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='test-', dir=output) as temp:
    os.environ['LOCALAPPDATA'] = temp
    settings = QSettings(str(Path(temp) / 'prefs.ini'), QSettings.Format.IniFormat)
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    settings.setValue('character_selection', 'refined')
    settings.setValue('random_walk', False)
    pet = Pet(data_dir=Path(temp) / 'data', settings=settings, startup=NoStartup())
    try:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.hide()
        pet.toolbar.hide()
        pet.bubble.hide()
        pet.dock_edge = ''
        pet.dock_reveal = pet.dock_target = 1
        pet.show()
        pet.set_mode('idle')
        spec = pet.walk_spec
        assert spec is not None and pet.live2d_renderer is None
        frames = []
        bounds = pet.screen_bounds()
        for direction, side in ((-1, 'left'), (1, 'right')):
            pet.move(bounds.left() + (bounds.width() - pet.width()) // 2, bounds.top() + 20)
            pet.grab().save(str(output / f'{side}-idle.png'))
            frames.append(pet.grab().toImage())
            start_x = pet.x()
            assert pet.start_walk(direction=direction, cycles=1)
            seen = {}
            for _ in range(math.ceil((spec.cycle_seconds + 1) / .025)):
                pet.tick_walk(.025)
                if not pet.walk_controller.active:
                    break
                key = spec.frame_key(side, pet.walk_controller.elapsed)
                if key not in seen:
                    image = pet.grab().toImage()
                    assert not pet.hit_region.isEmpty()
                    assert image.save(str(output / (key.replace(':', '-') + '.png')))
                    seen[key] = image
            assert len(seen) == spec.frame_count
            frames.extend(seen.values())
            assert not pet.walk_controller.active
            assert direction * (pet.x() - start_x) > 0
            assert not pet.dock_edge and pet.behavior.activity == 'idle'
        columns = spec.frame_count + 1
        sheet = QImage(pet.width() * columns, pet.height() * 2, QImage.Format.Format_ARGB32)
        sheet.fill(QColor('#e5ebf0'))
        painter = QPainter(sheet)
        for index, image in enumerate(frames):
            painter.drawImage((index % columns) * pet.width(), (index // columns) * pet.height(), image)
        painter.end()
        assert sheet.save(str(output / 'runtime-contact-sheet.png'))
        # Capability follows the installed native model, including older exports.
        if pet.set_variant('live2d'):
            from live2d_motion import MotionLibrary
            renderer = pet.live2d_renderer
            installed = MotionLibrary(renderer.motions.root)
            installed.validate_walk_model(renderer.parameter_ids, renderer.parts)
            assert pet.walk_supported() == (installed.walk_spec is not None)
            assert pet.walk_spec == installed.walk_spec
            assert not pet.grab().isNull()
        print('PASS: local walking frames, both directions move and finish, no docking, existing Live2D capability gate')
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
