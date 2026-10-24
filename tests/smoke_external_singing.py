"""Exercise opt-in external leg rigs through the real Qt pet paint path.

Uses synthetic sprites only; no downloaded or private character art is needed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from character_packs import STATES, read_pack, validate_images
from desktop_pet import DesktopPet
from pet_behavior import PetBehavior


class SpriteCanvas(QWidget):
    """Use production frame preparation and painting without audio or user data."""
    prepare_frames = DesktopPet.prepare_frames
    paintEvent = DesktopPet.paintEvent

    def __init__(self, pack):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.scale = 1
        self.resize(260, 310)
        self.live2d_renderer = None
        self.drag_dock_edge = ''
        self.behavior = PetBehavior('sing')
        self.phase = 1.2
        self.set_pack(pack)

    def set_pack(self, pack):
        images = validate_images(pack)
        loaded = {path: QPixmap.fromImage(images[state]) for state, path in pack.states.items()}
        self.frames = {state: loaded[pack.state_path(state)] for state in STATES}
        self.character_pack = pack
        self.anchors = pack.anchors
        self.prepare_frames()

    def dock_transform(self):
        return QTransform()

    def interaction_transform(self, activity):
        return QTransform()

    def current_music_beat(self, activity):
        return None


app = QApplication([])
with tempfile.TemporaryDirectory(prefix='deskpet-singing-') as temp:
    root = Path(temp)
    colors = {'idle': '#d08020', 'sing-front': '#f02020',
              'sing-left': '#20d040', 'sing-right': '#2040f0'}
    for state, color in colors.items():
        image = QImage(200, 250, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.fillRect(40, 20, 120, 145, QColor(color))
        painter.fillRect(55, 160, 22, 79, QColor(color))
        painter.fillRect(122, 160, 22, 79, QColor(color))
        painter.end()
        assert image.save(str(root / (state + '.png')))
    descriptor = {'version': 1, 'id': 'singing-test', 'name': 'Singing test',
                  'states': {state: state + '.png' for state in colors},
                  'anchors': {'head': [.5, .22], 'feet': [.5, .96]}}

    def load():
        (root / 'character.json').write_text(json.dumps(descriptor), encoding='utf-8')
        return read_pack(root)

    legacy_pack = load()
    canvas = SpriteCanvas(legacy_pack)
    assert not canvas.singing_rigs, 'existing external packs must remain undeformed'
    assert not canvas.grab().isNull()

    descriptor['singing_motion'] = {'legs': True, 'hem': .65}
    pack = load()
    canvas.set_pack(pack)
    assert set(canvas.singing_rigs) == {'sing-front', 'sing-left', 'sing-right'}
    for rig in canvas.singing_rigs.values():
        assert rig.hem == round(rig.pixmap.height() * .65)
        frames = []
        for moment in (.0, .3, .9):
            image = QImage(rig.pixmap.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            region = rig.draw(painter, moment, 1)
            painter.end()
            assert not region.isEmpty()
            frames.append(image)
        assert frames[0] != frames[1], 'opted-in legs must actually move'
        assert frames[0].copy(0, 0, rig.pixmap.width(), rig.hem) == frames[1].copy(
            0, 0, rig.pixmap.width(), rig.hem), 'head, body and microphone must stay intact'

    # Each pose has its own solid color: any lingering previous direction, even
    # translucent, is detectable. Compare reused canvas with a fresh widget too.
    for phase, channel in ((1.2, 2), (3.6, 1), (4.8, 0), (1.2, 2)):
        canvas.phase = phase
        frame = canvas.grab().toImage()
        assert not canvas.hit_region.isEmpty()
        visible = 0
        for y in range(frame.height()):
            for x in range(frame.width()):
                pixel = frame.pixelColor(x, y)
                if pixel.alpha() >= 16:
                    channels = (pixel.red(), pixel.green(), pixel.blue())
                    assert channels[channel] > max(value for i, value in enumerate(channels)
                                                   if i != channel), (phase, x, y, channels)
                    visible += 1
        assert visible > 1000
        fresh = SpriteCanvas(pack)
        fresh.phase = phase
        assert frame == fresh.grab().toImage(), 'turning must not retain previous frame pixels'
        fresh.close()
        fresh.deleteLater()
        app.processEvents()

    descriptor['singing_motion'] = {'legs': True, 'hem': .70}
    canvas.set_pack(load())
    assert all(rig.hem == round(rig.pixmap.height() * .70)
               for rig in canvas.singing_rigs.values())
    canvas.set_pack(legacy_pack)
    assert not canvas.singing_rigs, 'switching back to a legacy pack must discard custom rigs'
    assert not canvas.grab().isNull()
    canvas.set_pack(load())
    assert canvas.singing_rigs
    descriptor['singing_motion'] = {'legs': False, 'hem': .70}
    canvas.set_pack(load())
    assert not canvas.singing_rigs, 'switching off must discard old rigs'
    assert not canvas.grab().isNull()
    canvas.close()
    canvas.deleteLater()
    app.processEvents()

print('PASS: external default/opt-in/legacy-switch/disable, custom hem, real moving legs, intact upper body, '
      'single-pose turns and cleared previous pixels')
