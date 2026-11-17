"""External model contracts without depending on private artwork or an OpenGL device."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from PySide6.QtGui import QImage
from deskpet.pet.characters import read_pack
from deskpet.pet.live2d_pack import read_live2d_spec
from deskpet.animation.live2d_motion import MotionLibrary
from deskpet.animation.live2d_renderer import Live2DRenderer


class ExternalLive2DTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pack = Path(self.temp.name)/'pack'
        self.root = self.pack/'model'
        self.root.mkdir(parents=True)
        self.config = {'directory':'model', 'scale':1.4, 'hands':[[.3,.5],[.7,.5]]}
        image = QImage(16,16,QImage.Format.Format_ARGB32)
        image.fill(0);image.setPixel(8,8,0xffffffff)
        image.save(str(self.pack/'idle.png'));image.save(str(self.root/'texture.png'))
        (self.root/'model.moc3').write_bytes(b'MOC3fixture-for-validation-only')
        self.model = {'Version':3, 'FileReferences':{'Moc':'model.moc3', 'Textures':['texture.png'],
            'Motions':{key:[{'File':'motion.json'}] for key in ('Idle','CustomSong','CustomRub')}}}
        self.mapping = {'schemaVersion':1,'profile':'character','model':'model.model3.json',
            'renderScale':.75,'poseGroups':[],
            'activities':{'idle':'Idle','sing':'CustomSong','head_rub':'CustomRub'},
            'integrationRules':{'resetParameters':{'ParamAngleX':0, 'ParamPose':0}}}
        self.motion = {'Version':3,'Meta':{'Duration':2,'Loop':True},'Curves':[
            {'Target':'Parameter','Id':'ParamAngleX','Segments':[0,0,0,1,12,0,2,0]},
            {'Target':'Parameter','Id':'ParamPose','Segments':[0,0]}]}
        self.save()

    def save(self):
        for filename,data in [('model.model3.json',self.model),('action-map.json',self.mapping),('motion.json',self.motion)]:
            (self.root/filename).write_text(json.dumps(data),encoding='utf-8')

    def load(self):
        self.save()
        return read_live2d_spec(self.pack,self.config)

    def test_old_pack_is_unchanged_and_extension_is_discovered(self):
        self.assertIsNone(read_pack(self.pack).live2d)
        (self.pack/'character.json').write_text(json.dumps({'version':1,'id':'test','name':'Test',
            'states':{'idle':'idle.png'},'live2d':self.config}),encoding='utf-8')
        spec=read_pack(self.pack).live2d
        self.assertEqual(spec.root,self.root.resolve())
        self.assertEqual(spec.scale_for('sleep'),1.4)
        self.assertEqual(spec.hands,((.3,.5),(.7,.5)))

    def test_custom_actions_do_not_inherit_tianyi_choreography(self):
        self.load()
        library=MotionLibrary(self.root)
        for activity,group in [('sing','CustomSong'),('head_rub','CustomRub')]:
            self.assertEqual(library.group_for(activity),group)
            self.assertEqual(library.sample(activity,1)[0],{'ParamAngleX':12,'ParamPose':0})
        self.assertEqual(library.sample('sing',.5),library.sample('sing',2.5))
        self.assertEqual(library.group_for('unknown'),'Idle')

    def test_all_resources_stay_in_model_directory(self):
        for key,value in [('Moc','../outside.moc3'),('Textures',['../outside.png']),
                          ('DisplayInfo','../outside.json')]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.model)
                self.model['FileReferences'][key]=value
                with self.assertRaises(ValueError):self.load()
                self.model=original
        self.mapping['model']='../escape.model3.json'
        with self.assertRaises(ValueError):self.load()

    def test_missing_or_corrupt_resource_is_rejected_before_native_loading(self):
        (self.root/'model.moc3').write_bytes(b'not-a-model')
        with self.assertRaisesRegex(ValueError,'文件头'):self.load()
        (self.root/'model.moc3').write_bytes(b'MOC3')
        (self.root/'texture.png').unlink()
        with self.assertRaises(ValueError):self.load()

    def test_invalid_and_unbounded_curves_are_rejected(self):
        for segments in ([0,0,0,.5], [0,0,0,-1,1], [0,0,0,3,1],
                         [0,0,99,1,1], [0,float('nan')], [0,0,1,.8,0,.1,1,1,1]):
            self.motion['Curves'][0]['Segments']=segments
            with self.subTest(segments=segments), self.assertRaises(ValueError):self.load()

    def test_unknown_parameter_and_missing_pose_groups_are_rejected(self):
        self.motion['Curves'][0]['Id']='NotDeclared'
        with self.assertRaises(ValueError):self.load()
        self.motion['Curves'][0]['Id']='ParamAngleX'
        del self.mapping['poseGroups']
        with self.assertRaises(ValueError):self.load()

    def test_view_geometry_limits(self):
        for key,value in [('scale',float('inf')),('scale',True),('scale',3),
                          ('head',[.9,.5,.2,.2]),('feet',[-.1,1]),
                          ('pose_scale',{'sleep':2}),('hands',[]),('hands',[[1.1,.5]])]:
            old=copy.deepcopy(self.config);self.config[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):self.load()
            self.config=old
        self.mapping['renderScale']=0
        with self.assertRaises(ValueError):self.load()

    def test_missing_native_parameters_or_parts_reject_model_switch(self):
        library=MotionLibrary(self.root)
        with self.assertRaisesRegex(RuntimeError,'参数'):
            Live2DRenderer._validate_generic_model(library,{'ParamAngleX'}, {})
        self.motion['Curves'].append({'Target':'PartOpacity','Id':'AbsentPart','Segments':[0,1]})
        self.save();library=MotionLibrary(self.root)
        with self.assertRaisesRegex(RuntimeError,'部件'):
            Live2DRenderer._validate_generic_model(library,{'ParamAngleX','ParamPose'}, {})

    def test_part_visibility_must_reset_in_every_motion(self):
        self.mapping['poseGroups']=[['Stand','Sleep']]
        with self.assertRaisesRegex(ValueError,'完整声明'):self.load()
        self.motion['Curves'] += [
            {'Target':'PartOpacity','Id':'Stand','Segments':[0,1]},
            {'Target':'PartOpacity','Id':'Sleep','Segments':[0,0]}]
        self.load()
        self.motion['Curves'][-1]['Segments']=[0,2]
        with self.assertRaises(ValueError):self.load()

    def test_utf8_bom_supported_consistently_by_loader(self):
        for path in self.root.glob('*.json'):
            data=path.read_text('utf-8');path.write_text(data,encoding='utf-8-sig')
        read_live2d_spec(self.pack,self.config)
        self.assertEqual(MotionLibrary(self.root).sample('sing',1)[0]['ParamAngleX'],12)


if __name__=='__main__':unittest.main()
