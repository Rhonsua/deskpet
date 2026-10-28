"""Real Qt integration with synthetic PNG frames; no user settings or API calls."""
import json
import os
from pathlib import Path
import random
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings, Qt, QPoint
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import Pet
from visual_style import APPEARANCE_REVISION
from walk_controller import WalkController, WALK_SPEED_MULTIPLIER


class NoStartup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
output = ROOT / 'preview/walk-integration'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='test-', dir=output) as directory:
    root = Path(directory)
    os.environ['LOCALAPPDATA'] = str(root)
    folder = root / 'characters/test-walk'
    folder.mkdir(parents=True)
    names = ['idle'] + [f'{side}-{i}' for side in ('left', 'right') for i in range(4)]
    for i, name in enumerate(names):
        frame = QImage(64, 96, QImage.Format.Format_ARGB32)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.fillRect(12, 8, 40, 85, QColor.fromHsv(i * 35, 180, 220))
        painter.end()
        assert frame.save(str(folder / (name + '.png')))
    manifest = {'version': 1, 'id': 'walk-test', 'name': 'Test', 'states': {'idle': 'idle.png'},
                'walk': {'left': [f'left-{i}.png' for i in range(4)],
                         'right': [f'right-{i}.png' for i in range(4)], 'fps': 4, 'stride': 20}}
    (folder / 'character.json').write_text(json.dumps(manifest), encoding='utf-8')
    settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    settings.setValue('character_selection', 'external:test-walk')
    settings.setValue('random_walk', False)
    pet = Pet(data_dir=root / 'data', settings=settings, startup=NoStartup(),
              characters_dir=root / 'characters')
    try:
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.hide()
        pet.toolbar.hide()
        pet.bubble.hide()
        pet.dock_edge = ''
        bounds = pet.screen_bounds()
        pet.move(bounds.left() + 40, bounds.top() + 30)
        pet.show()
        app.processEvents()
        pet.walk_controller = WalkController(rng=random.Random(3))
        assert pet.walk_supported() and pet.panel.walk_button.isEnabled()
        assert len(pet.walk_frames) == 8
        pet.set_mode('listen')
        assert pet.start_walk(direction=1, cycles=1)
        start = pet.x()
        for _ in range(5):
            # Observe mid-walk even as the configured pace increases.
            pet.tick_walk(.1 / WALK_SPEED_MULTIPLIER)
        assert pet.x() > start and pet.behavior.activity == 'walk-right'
        assert pet.behavior.mode == 'listen' and not pet.dock_edge
        key = pet.walk_spec.frame_key('right', pet.walk_controller.elapsed)
        assert key != 'walk-right:0'
        pet.grab()
        point = pet.hit_region.boundingRect().center()
        QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=point)
        assert not pet.walk_controller.active and pet.behavior.activity == 'idle'
        pet.begin_drag()
        assert pet.behavior.activity == 'lift'
        QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=point)
        pet.behavior.tick(1)
        assert pet.behavior.mode == 'listen' and not pet.behavior.layers
        pet.click_timer.stop()
        pet.dock_edge = ''
        pet.set_mode('idle')
        pet.last_interaction -= 20
        assert pet.start_walk(direction=1, automatic=True, cycles=1)
        deadline = pet.walk_controller.cooldown_until
        assert float(settings.value('walk_cooldown_until')) == deadline
        pet.set_mode('sleep')
        assert not pet.walk_controller.active and not pet.start_walk()
        pet.set_mode('idle')
        assert pet.start_walk(direction=-1, cycles=1)
        assert pet.walk_controller.cooldown_until == deadline
        pet.open_tools(2)
        assert not pet.walk_controller.active
        pet.panel.hide()
        assert not pet.start_walk(automatic=True)
        assert pet.start_walk(direction=1, cycles=1)
        for _ in range(30):
            pet.tick_walk(.1)
        assert not pet.walk_controller.active and pet.behavior.activity == 'idle'
        assert not pet.dock_edge
        assert pet.start_walk(direction=-1, cycles=1)
        pet.hide()
        assert not pet.walk_controller.active and not pet.behavior.layers
        pet.show()
        assert pet.start_walk(direction=-1, cycles=1)
        pet.playing = True
        pet.tick_walk(.1)
        assert not pet.walk_controller.active and pet.behavior.activity == 'sing'
        pet.playing = False
        # Packs without walk stay supported and never slide an idle picture.
        del manifest['walk']
        (folder / 'character.json').write_text(json.dumps(manifest), encoding='utf-8')
        assert pet.set_variant('external:test-walk')
        assert not pet.walk_supported() and not pet.panel.walk_button.isEnabled()
        assert not pet.start_walk()
        print('PASS: sequence timing, manual/automatic cooldown, click/drag/state/tool/hide/playback interrupts, old packs')
    finally:
        pet.timer.stop()
        pet.fold_timer.stop()
        pet.click_timer.stop()
        pet.hold_timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.watchdog.stop()
        pet.panel.shutdown_audio()
        pet.tray.hide()
        pet.hide()
        pet.panel.hide()
        pet.panel.store.close()
        pet.deleteLater()
        app.processEvents()
