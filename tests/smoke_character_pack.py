"""Test a supplied local pack without publishing its artwork or changing user data.

Usage: python tests/smoke_character_pack.py characters/my-pack
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication
from character_packs import read_pack, validate_images, STATES
from main import Pet
from pet_behavior import PetBehavior
from visual_style import APPEARANCE_REVISION

app = QApplication([])
folder = Path(sys.argv[1]).resolve()
images = validate_images(read_pack(folder))
assert set(images) == set(STATES), 'this check expects a complete ten-state pack'
output = root / 'preview' / 'character-pack-check'
output.mkdir(parents=True, exist_ok=True)

class NoStartup:
    supported = False
    def enabled(self): return False

with tempfile.TemporaryDirectory(prefix='test-', dir=output) as temp:
    scratch = Path(temp)
    os.environ['LOCALAPPDATA'] = temp
    packs = scratch / 'characters'
    shutil.copytree(folder, packs / folder.name)
    selected = 'external:' + folder.name
    settings = QSettings(str(scratch / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', selected)
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    def make():
        return Pet(data_dir=scratch / 'data', settings=settings,
                   startup=NoStartup(), characters_dir=packs)
    def dispose(pet):
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.store.close()
        pet.tray.hide()
        pet.hide()
        pet.close_live2d()
        pet.deleteLater()
        app.processEvents()
    pet = make()
    try:
        assert pet.variant == selected and pet.character_pack is not None
        pet.timer.stop()
        assert len({image.cacheKey() for image in pet.frames.values()}) == 10
        assert not pet.singing_rigs
        before = dict(pet.panel.store.pet())
        sheet = QImage(320*5, 360*2, QImage.Format.Format_ARGB32)
        sheet.fill(QColor('#edf1f7'))
        p = QPainter(sheet)
        p.setFont(QFont('Segoe UI', 10))
        for i, state in enumerate(('idle','happy','eat','lift','sleep','phone','sing-front','sing-left','sing-right','blink')):
            pet.behavior = PetBehavior()
            if state in ('sleep','phone','idle'):
                pet.set_mode(state)
            elif state.startswith('sing-'):
                pet.set_mode('sing')
                pet.phase = {'sing-front':4.8,'sing-left':1.2,'sing-right':3.6}[state]
            elif state == 'blink':
                pet.phase = 4.81
            else:
                pet.behavior.react(state, 20)
                pet.behavior.layers[-1].elapsed = .6
            app.processEvents()
            shot = pet.grab()
            assert not shot.isNull() and not pet.hit_region.isEmpty(), state
            tile = shot.scaled(310, 330, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            x,y=(i%5)*320,(i//5)*360
            p.drawPixmap(x,y+20,tile)
            p.drawText(x+10,y+15,state)
            pet.phase = 1
        p.end()
        assert sheet.save(str(output / (folder.name + '-runtime.png')))
        pet.set_mode('sleep')
        pet.behavior.tick(2)
        pet.behavior.begin_drag()
        pet.behavior.tick(1)
        pet.behavior.end_drag()
        pet.behavior.tick(.65)
        assert pet.sleeping and pet.behavior.activity_elapsed == 2
        for edge in ('left','right','top','bottom'):
            pet.set_mode('idle')
            pet.dock_edge,pet.dock_reveal=edge,0
            pet.grab()
            assert not pet.hit_region.isEmpty(), edge
        pet.dock_edge = ''
        pet.playing = True
        assert pet.behavior.activity == 'sing'
        pet.playing = False
        assert pet.behavior.activity == 'idle'
        after = dict(pet.panel.store.pet())
        assert before['level'] == after['level'] and before['notes'] == after['notes']
        assert pet.set_variant('simple') and pet.set_variant(selected)
        pet.set_mode('sleep')
    finally:
        dispose(pet)
    pet = make()
    try:
        assert pet.variant == selected and pet.sleeping
    finally:
        dispose(pet)
(output / (folder.name+'-report.json')).write_text(json.dumps(
    {'ok':True,'states':10,'pack':folder.name,'persistence':True,'drag_resume':True,
     'four_edges':True,'music_state':True,'shared_growth':True},indent=2),encoding='utf-8')
print('PASS: complete pack, real Qt poses, switching, persistence, drag resume, four edges and shared music/growth')
