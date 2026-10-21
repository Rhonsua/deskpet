"""Native choreography, gesture entry points and input-transparent visual layer."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings, QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from main import Pet
from pet_behavior import PetBehavior, MODES
from singing_choreography import footwork

app = QApplication([])
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'preview/live2d/dance-review'
OUT.mkdir(parents=True, exist_ok=True)


class NoStartup:
    supported = False
    def enabled(self):
        return False


def capture(pet, activity, seconds):
    pet.behavior = PetBehavior(activity if activity in MODES else 'idle')
    if activity in MODES:
        pet.behavior.mode_elapsed = seconds
    else:
        pet.behavior.react(activity, 10)
        pet.behavior.layers[-1].elapsed = seconds
    pet.phase = seconds
    pet.live2d_frame_key = None
    pet.update_live2d_geometry(activity)
    pet.grab()  # Update the same body silhouette used by the decorative layer.
    pet.effects.sync()
    effects = pet.effects.grab()
    body = pet.grab()
    image = QImage(pet.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor('#e7edf3'))
    painter = QPainter(image)
    painter.drawPixmap(0, 0, effects)
    painter.drawPixmap(0, 0, body)
    painter.end()
    return image


with tempfile.TemporaryDirectory(prefix='test-', dir=OUT) as temp:
    os.environ['LOCALAPPDATA'] = temp
    settings = QSettings(str(Path(temp)/'settings.ini'), QSettings.Format.IniFormat)
    pet = Pet(data_dir=Path(temp)/'data', settings=settings, startup=NoStartup())
    try:
        pet.timer.stop()
        assert pet.live2d_renderer is not None
        assert pet.effects.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert pet.effects.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert pet.effects.focusPolicy() == Qt.FocusPolicy.NoFocus
        capture(pet, 'sing', .4)
        old_hit = pet.hit_region
        fx = pet.effects.grab().toImage()
        dpr = fx.devicePixelRatio()
        inside = 0
        for y in range(0, pet.height(), 3):
            for x in range(0, pet.width(), 3):
                if old_hit.contains(QPoint(x, y)):
                    inside += 1
                    assert fx.pixelColor(int((x+.5)*dpr), int((y+.5)*dpr)).alpha() == 0, 'effect covers body'
        assert inside > 100
        pet.panel.effects_toggle.setChecked(False)
        pet.effects.sync()
        assert not pet.effects.isVisible()
        pet.grab()
        assert pet.hit_region == old_hit, 'decorations must not expand click region'
        pet.panel.effects_toggle.setChecked(True)
        pet.effects.sync()
        pet.move(pet.pos()+QPoint(-15, -15))
        assert pet.effects.geometry() == pet.geometry()
        pet.dock_edge = 'left'
        pet.effects.sync()
        assert not pet.effects.isVisible()
        pet.dock_edge = ''
        pet.effects.sync()
        pet.hide()
        assert not pet.effects.isVisible()
        pet.show()

        # Exercise the actual desktop poller without moving the user's pointer.
        pet.behavior = PetBehavior('sing')
        pet.live2d_frame_key = None
        pet.grab()
        head = pet.head_region.boundingRect().center()
        before_growth = dict(pet.panel.store.pet())
        for dx in (0, 24, -24, 24, -24):
            position = pet.pos()+head+QPoint(dx, 0)
            with patch.object(QCursor, 'pos', return_value=position):
                pet.last_frame_time = time.monotonic()-.1
                pet.animate()
            if pet.behavior.activity == 'head_rub':
                break
        assert pet.behavior.activity == 'head_rub', 'head gesture did not reach runtime action'
        resumed_time = pet.behavior.mode_elapsed
        pet.behavior.tick(2.2)
        assert pet.behavior.activity == 'sing'
        assert abs(pet.behavior.mode_elapsed-resumed_time) < 1e-6
        hand = pet.pos()+QPoint(round(pet.width()/2-62*pet.scale), round(185*pet.scale))
        for _ in range(16):
            with patch.object(QCursor, 'pos', return_value=hand):
                pet.last_frame_time = time.monotonic()-.1
                pet.animate()
            if pet.behavior.activity == 'mouse_wave':
                break
        assert pet.behavior.activity == 'mouse_wave', 'hand dwell did not reach runtime action'
        assert dict(pet.panel.store.pet()) == before_growth, 'automatic gestures must not farm rewards'

        actions = [('sing', .3), ('sing', 5.5), ('sing', 11.4), ('sing', 16.95),
                   ('head_rub', .8), ('mouse_wave', 1.2), ('sleep', 3), ('phone', 3),
                   ('eat', 1.4), ('lift', .1), ('land', .2), ('idle', .5)]
        sheet = QImage(1040, 990, QImage.Format.Format_ARGB32)
        sheet.fill(QColor('#e7edf3'))
        painter = QPainter(sheet)
        for i, (activity, t) in enumerate(actions):
            image = capture(pet, activity, t)
            image.save(str(OUT/f'polish-{activity}-{t}.png'))
            x, y = (i % 4)*260, (i//4)*330
            painter.setPen(QColor('#394c5b'))
            painter.drawText(x+5, y+15, f'{activity}  {t}s')
            fitted = image.scaled(260, 310, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            painter.drawImage(x+(260-fitted.width())//2, y+20, fitted)
        painter.end()
        sheet.save(str(OUT/'polish-overview.png'))

        # Full 19.2-second source/part cycle with decorations, at 15 preview FPS.
        if '--quick' not in sys.argv:
            gif = []
            for i in range(288):
                image = capture(pet, 'sing', i/15).convertToFormat(QImage.Format.Format_RGBA8888)
                frame = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.bits()))
                gif.append(frame.convert('RGB').resize((256, 305), Image.Resampling.LANCZOS))
            gif[0].save(OUT/'sing-with-effects.gif', save_all=True,
                        append_images=gif[1:], duration=67, loop=0)
        print('PASS: real head/hand gestures, no reward farming, clock resume, body-excluded transparent effects, visibility/geometry, 12 poses'
              + ('.' if '--quick' in sys.argv else ', full decorated cycle.'))
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
