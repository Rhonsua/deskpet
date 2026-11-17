"""Real Qt/OpenGL check for a supplied private Live2D pack, with isolated settings.

Usage: python -B tests/smoke_external_live2d.py characters/my-pack
No artwork, account settings or installed character selection is published/changed.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QSettings, QPointF, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PIL import Image,ImageDraw
from deskpet.app import Pet
from deskpet.pet.behavior import PetBehavior
from deskpet.pet.characters import read_pack
from deskpet.ui.appearance import APPEARANCE_REVISION
from deskpet.animation.live2d_renderer import MODEL_ROOT

app=QApplication([])
source=Path(sys.argv[1]).resolve()
assert read_pack(source).live2d is not None
out=ROOT/'preview/external-live2d'/source.name
out.mkdir(parents=True,exist_ok=True)

class NoStartup:
    supported=False
    def enabled(self):return False

with tempfile.TemporaryDirectory(prefix='isolated-',dir=out) as temp:
    scratch=Path(temp)
    os.environ['LOCALAPPDATA']=str(scratch)
    packs=scratch/'characters'
    shutil.copytree(source,packs/source.name)
    selected='external:'+source.name
    settings=QSettings(str(scratch/'settings.ini'),QSettings.Format.IniFormat)
    settings.setValue('character_selection',selected)
    settings.setValue('appearance_revision',APPEARANCE_REVISION)
    pet=Pet(data_dir=scratch/'data',settings=settings,startup=NoStartup(),characters_dir=packs)
    report={}
    try:
        pet.timer.stop();pet.tray.hide();pet.panel.hide();pet.toolbar.hide();pet.bubble.hide()
        assert pet.variant==selected,pet.panel.character_note.text()
        renderer=pet.live2d_renderer
        assert renderer is not None and renderer.motions.generic
        assert not renderer.crawl_available and not renderer.work_available
        before=dict(pet.panel.store.pet())
        cases=[('idle',0),('sing',.6),('sing',1.8),('sing',3),('sleep',2),('phone',2),
               ('eat',.7),('lift',.7),('happy',.8),('mouse_wave',.6),('head_rub',.9),('land',.2)]
        sheet=Image.new('RGB',(340*4,350*3),'#e9edf2')
        def pose(activity,elapsed):
            pet.behavior=PetBehavior()
            if activity in ('idle','sing','sleep','phone'):
                pet.behavior.set_mode(activity);pet.behavior.mode_elapsed=elapsed
            else:
                pet.behavior.react(activity,20);pet.behavior.layers[-1].elapsed=elapsed
            if activity=='lift':pet.drag_anchor=QPointF(pet.width()/2,100)
            pet.update_live2d_geometry(activity)
            pet.live2d_frame_key=None
            return pet.grab()
        for i,(activity,elapsed) in enumerate(cases):
            started=time.perf_counter()
            pixmap=pose(activity,elapsed)
            assert pet.live2d_renderer is renderer and pet.variant==selected
            assert not pixmap.isNull() and not pet.hit_region.isEmpty(),activity
            assert not pet.head_region.isEmpty(),activity
            bounds=pet.hit_region.boundingRect()
            assert bounds.left()>0 and bounds.right()<pet.width()-1,(activity,bounds)
            name=f'{activity}-{elapsed}'
            pixmap.save(str(out/f'{name}.png'))
            im=Image.open(out/f'{name}.png').convert('RGBA')
            im=im.resize((pet.width(),pet.height()),Image.Resampling.LANCZOS)
            tile=Image.new('RGBA',(340,350),'#e9edf2')
            tile.alpha_composite(im,((340-im.width)//2,24))
            ImageDraw.Draw(tile).text((12,8),name,fill='#142838')
            sheet.paste(tile.convert('RGB'),((i%4)*340,(i//4)*350))
            report[name]={'window':(pet.width(),pet.height()),'bounds':bounds.getRect(),
                          'head':pet.head_region.boundingRect().getRect(),
                          'frame_ms':round((time.perf_counter()-started)*1000,1)}
        sheet.save(out/'desktop-actions.jpg',quality=94)
        # Mapped poses must stay exclusive and restore the saved mode after drag.
        pet.behavior=PetBehavior('sleep');pet.behavior.tick(2)
        pet.behavior.begin_drag();pet.behavior.tick(1);pet.behavior.end_drag();pet.behavior.tick(.8)
        assert pet.behavior.activity=='sleep'
        if 'ParamPose' in renderer.parameter_ids:
            assert renderer.motions.sample(pet.behavior.activity,pet.behavior.activity_elapsed)[0]['ParamPose']==1
        pet.update_live2d_geometry('sleep');pet.grab()
        pet.behavior.react('eat',2.8);pet.behavior.tick(2.9)
        assert pet.behavior.activity=='sleep'
        # Actual mouse click uses this model's head region.
        pose('idle',0)
        QTest.mouseClick(pet,Qt.MouseButton.LeftButton,pos=pet.head_region.boundingRect().center())
        assert pet.touch_head
        pet.click_timer.stop();pet.hold_timer.stop();pet.press_point=None
        # One renderer/context is reused between native models; failure is transactional.
        if (MODEL_ROOT/'action-map.json').is_file():
            assert pet.set_variant('live2d'),pet.panel.character_note.text()
            assert pet.live2d_renderer is renderer and not renderer.motions.generic
            assert not pose('sing',.8).isNull()
            assert pet.set_variant(selected),pet.panel.character_note.text()
            assert pet.live2d_renderer is renderer and renderer.motions.generic
        mapping_path=read_pack(packs/source.name).live2d.root/'action-map.json'
        original=mapping_path.read_text('utf-8');mapping=json.loads(original)
        mapping['integrationRules']['resetParameters']['MissingNativeParameter']=0
        mapping_path.write_text(json.dumps(mapping),encoding='utf-8')
        assert pet.set_variant(selected) is False
        assert pet.live2d_renderer is renderer and pet.variant==selected
        assert not pose('idle',0).isNull()
        mapping_path.write_text(original,encoding='utf-8')
        # A PNG switch releases GL, and switching back re-creates a usable renderer.
        assert pet.set_variant('refined') and pet.live2d_renderer is None
        assert pet.set_variant(selected),pet.panel.character_note.text()
        renderer=pet.live2d_renderer
        assert not pose('idle',0).isNull()
        # Four edge peeks remain stable across repaint; no transformed-anchor feedback.
        for edge in ('left','right','top','bottom'):
            pet.dock_edge=edge;pet.dock_reveal=pet.dock_target=.65
            pet.grab();head=pet.character_head()
            region=pet.head_region.boundingRect()
            for _ in range(5):pet.grab()
            assert pet.character_head()==head and pet.head_region.boundingRect()==region,edge
            assert not pet.hit_region.isEmpty(),edge
        pet.dock_edge='';pet.dock_reveal=pet.dock_target=1
        for scale in (.75,1.5,1):
            pet.set_scale(scale);size=pet.size();pet.update_live2d_geometry('idle')
            assert pet.size()==size,'scale setting and animation must agree on window geometry'
        pet.drag_anchor=QPointF(pet.width()/2,70)
        pet.behavior=PetBehavior();pet.behavior.begin_drag();pet.behavior.tick(.1)
        assert (pet.interaction_transform('lift').map(pet.drag_anchor)-pet.drag_anchor).manhattanLength()<1e-5
        assert dict(pet.panel.store.pet())==before,'visual checks must not change growth'
        settings.sync()
        assert QSettings(str(scratch/'settings.ini'),QSettings.Format.IniFormat).value('character_selection')==selected
        frames=[]
        for i in range(58):
            shot=pose('sing',i/12);path=out/'animation-frame.png';shot.save(str(path))
            im=Image.open(path).convert('RGBA');bg=Image.new('RGBA',im.size,'#edf1f6');bg.alpha_composite(im)
            frames.append(bg.convert('RGB'))
        frames[0].save(out/'sing-desktop.gif',save_all=True,append_images=frames[1:],duration=83,loop=0)
        (out/'animation-frame.png').unlink()
        report['checks']=['all mapped poses','transparent rendering','head hit test','sleep drag/food resume',
                          'native model switching','failed candidate keeps current model','PNG/native reload',
                          'stable four-edge docking','display scaling','pickup anchor','saved selection','growth unchanged']
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS:',', '.join(report['checks']))
        print('Preview:',out)
    finally:
        pet.timer.stop();pet.fold_timer.stop();pet.hold_timer.stop();pet.click_timer.stop()
        pet.panel.progress_timer.stop();pet.panel.bilibili.shutdown();pet.panel.shutdown_audio()
        pet.close_live2d();pet.tray.hide();pet.toolbar.hide();pet.bubble.hide();pet.panel.hide()
        pet.panel.store.close();pet.hide();pet.deleteLater();app.processEvents()
