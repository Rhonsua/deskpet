"""Optional Cubism walking contract without requiring an OpenGL model."""
import json
from pathlib import Path
import tempfile
import unittest

from live2d_motion import MotionLibrary


class Live2DWalkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mapping = {'model': 'model.json', 'activities': {'idle': 'Idle'},
                        'poseGroups': [['Standing', 'Walking']],
                        'integrationRules': {'resetParameters': {'ParamWalk': 0}},
                        'walk': {'left': 'WalkLeft', 'right': 'WalkRight', 'stride': 64}}
        self.motion = {'Meta': {'Loop': True, 'Duration': 1.2}, 'Curves': [
            {'Target': 'Parameter', 'Id': 'ParamWalk', 'Segments': [0, 0, 0, .6, 1, 0, 1.2, 0]},
            {'Target': 'PartOpacity', 'Id': 'Standing', 'Segments': [0, 0]},
            {'Target': 'PartOpacity', 'Id': 'Walking', 'Segments': [0, 1]}]}
        refs = {group: [{'File': group + '.json'}] for group in ('Idle', 'WalkLeft', 'WalkRight')}
        self.write('model.json', {'FileReferences': {'Motions': refs}})
        self.write('action-map.json', self.mapping)
        for group in refs:
            self.write(group + '.json', self.motion)

    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding='utf-8')

    def test_walk_uses_authored_group_and_shared_cycle_contract(self):
        library = MotionLibrary(self.root)
        self.assertEqual(library.walk_spec.cycle_seconds, 1.2)
        self.assertEqual(library.walk_spec.stride, 64)
        self.assertEqual(library.group_for('walk-left'), 'WalkLeft')
        self.assertEqual(library.group_for('walk-right'), 'WalkRight')
        parameters, parts = library.sample('walk-left', .6)
        self.assertEqual(parameters['ParamWalk'], 1)
        self.assertEqual(parts, {'Standing': 0, 'Walking': 1})
        self.assertEqual(library.sample('walk-left', 0), library.sample('walk-left', 1.2))

    def test_missing_capability_leaves_existing_model_supported(self):
        del self.mapping['walk']
        self.write('action-map.json', self.mapping)
        library = MotionLibrary(self.root)
        self.assertIsNone(library.walk_spec)
        library.sample('idle', .2)

    def test_missing_model_parameters_disable_walk(self):
        library = MotionLibrary(self.root)
        library.validate_walk_model({'ParamOther'})
        self.assertIsNone(library.walk_spec)
        self.assertTrue(library.walk_error)
        library = MotionLibrary(self.root)
        library.validate_walk_model({'ParamWalk'}, {'Standing'})
        self.assertIsNone(library.walk_spec)

    def test_unbounded_numbers_do_not_escape_optional_validation(self):
        for value in (float('nan'), float('inf'), 10**400):
            self.mapping['walk']['stride'] = value
            self.write('action-map.json', self.mapping)
            self.assertIsNone(MotionLibrary(self.root).walk_spec)
        self.mapping['walk']['stride'] = 64
        self.write('action-map.json', self.mapping)
        self.motion['Curves'][0]['Segments'][1] = float('nan')
        self.write('WalkLeft.json', self.motion)
        self.assertIsNone(MotionLibrary(self.root).walk_spec)

    def test_invalid_optional_motion_disables_walk_only(self):
        for kind in ('missing-file', 'no-reset', 'not-looping', 'different-duration', 'same-group'):
            with self.subTest(kind=kind):
                self.setUp()
                if kind == 'missing-file':
                    (self.root / 'WalkLeft.json').unlink()
                elif kind == 'no-reset':
                    self.mapping['integrationRules']['resetParameters'] = {}
                elif kind == 'same-group':
                    self.mapping['walk']['right'] = 'WalkLeft'
                elif kind == 'not-looping':
                    self.motion['Meta']['Loop'] = False
                    self.write('WalkLeft.json', self.motion)
                else:
                    self.motion['Meta']['Duration'] = 2
                    self.write('WalkLeft.json', self.motion)
                self.write('action-map.json', self.mapping)
                library = MotionLibrary(self.root)
                self.assertIsNone(library.walk_spec)
                self.assertTrue(library.walk_error)
                library.sample('idle', .2)


if __name__ == '__main__':
    unittest.main()
