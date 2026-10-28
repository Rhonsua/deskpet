"""Guard export validation against stale MOCs and modulo-hidden loop seams."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'experiments/live2d-tianyi/validate_walk_export.py'
if not SCRIPT.is_file():
    raise unittest.SkipTest('Local Cubism export validator is not part of the code-only checkout')
spec = importlib.util.spec_from_file_location('validate_walk_export', SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
prepare_spec = importlib.util.spec_from_file_location(
    'prepare_walk_runtime_for_validation_tests', SCRIPT.with_name('prepare_walk_runtime.py'))
preparer = importlib.util.module_from_spec(prepare_spec)
prepare_spec.loader.exec_module(preparer)
calibration_spec = importlib.util.spec_from_file_location(
    'calibrate_walk_ground_for_tests', SCRIPT.with_name('calibrate_walk_ground.py'))
calibrator = importlib.util.module_from_spec(calibration_spec)
calibration_spec.loader.exec_module(calibrator)


class WalkingExportValidatorTests(unittest.TestCase):
    def test_generated_gait_stays_inside_authored_ranges_without_double_swing(self):
        for direction in ('left', 'right'):
            for index in range(2001):
                values = preparer.gait(index * 2.16 / 2000, 2.16, direction)
                for key, value in values.items():
                    low = 0 if any(name in key for name in ('Knee', 'Bounce', 'Visible')) else -1
                    self.assertGreaterEqual(value, low, (direction, key))
                    self.assertLessEqual(value, 1, (direction, key))
                self.assertFalse(values['ParamWalkKneeL'] > 1e-8 and
                                 values['ParamWalkKneeR'] > 1e-8)
            self.assertEqual(preparer.gait(0, 2.16, direction), preparer.gait(2.16, 2.16, direction))

    def test_directional_hip_ranges_do_not_change_other_motion_tracks(self):
        left = preparer.make_motion('left', set(), 2.16)
        right = preparer.make_motion('right', set(), 2.16)
        for a, b in zip(left['Curves'], right['Curves']):
            if a['Id'] in ('ParamWalkHipL', 'ParamWalkHipR'):
                self.assertNotEqual(a['Segments'], b['Segments'])
            else:
                self.assertEqual(a, b)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base, self.stage = [Path(self.temp.name) / name for name in ('lift', 'walk')]
        self.base.mkdir()
        self.stage.mkdir()
        mapping = {'model': 'model.json', 'activities': {'idle': 'Idle'},
                   'poseGroups': [['Standing'], ['ArmRelax', 'ArmMic']],
                   'integrationRules': {'resetParameters': {'ParamAngleX': 0, 'ParamAngleZ': 0,
                                                            'ParamBodyAngleZ': 0}}}
        self.motion = {'Meta': {'Loop': True, 'Duration': 1.8}, 'Curves': [
            {'Target': 'Parameter', 'Id': 'ParamAngleX', 'Segments': [0, 0]},
            {'Target': 'PartOpacity', 'Id': 'Standing', 'Segments': [0, 1]},
            {'Target': 'PartOpacity', 'Id': 'ArmRelax', 'Segments': [0, 1]},
            {'Target': 'PartOpacity', 'Id': 'ArmMic', 'Segments': [0, 0]}]}
        self.write(self.base / 'action-map.json', mapping)
        self.write(self.base / 'idle.json', self.motion)
        self.write(self.base / 'sing.json', self.motion)
        self.write(self.base / 'wave.json', self.motion)
        refs = {'Idle': [{'File': 'idle.json'}], 'SingTurn': [{'File': 'sing.json'}],
                'Wave': [{'File': 'wave.json'}]}
        model = {'FileReferences': {'Moc': 'model.moc3', 'Textures': ['texture.png'], 'Motions': refs}}
        self.write(self.base / 'model.json', model)
        (self.base / 'model.moc3').write_bytes(b'old moc fixture')
        (self.base / 'texture.png').write_bytes(b'texture fixture')
        self.mapping = copy.deepcopy(mapping)
        self.mapping['walk'] = {'left': 'WalkLeft', 'right': 'WalkRight', 'stride': 42}
        self.mapping['poseGroups'][0].extend(['WalkingLeft', 'WalkingRight'])
        for parameters in validator.DEFAULT_BINDINGS['parameters'].values():
            self.mapping['integrationRules']['resetParameters'].update({key: 0 for key in parameters})
        self.write(self.stage / 'action-map.json', self.mapping)
        self.motion['Curves'].extend([
            {'Target': 'PartOpacity', 'Id': key, 'Segments': [0, 0]}
            for key in ('WalkingLeft', 'WalkingRight')])
        for file in ('idle.json', 'sing.json', 'wave.json'):
            self.write(self.stage / file, self.motion)
        for direction in ('Left', 'Right'):
            motion = copy.deepcopy(self.motion)
            for curve in motion['Curves']:
                if curve['Target'] == 'PartOpacity':
                    curve['Segments'] = [0, int(curve['Id'] == 'Walking' + direction)]
            for parameters in validator.DEFAULT_BINDINGS['parameters'].values():
                motion['Curves'].extend({'Target': 'Parameter', 'Id': key,
                                         'Segments': [0, 0, 0, .9, 1, 0, 1.8, 0]}
                                        for key in parameters)
            self.write(self.stage / f'walk-{direction.lower()}.json', motion)
            model['FileReferences']['Motions']['Walk' + direction] = [{'File': f'walk-{direction.lower()}.json'}]
        self.write(self.stage / 'model.json', model)
        (self.stage / 'model.moc3').write_bytes(b'fresh walk moc fixture')
        (self.stage / 'texture.png').write_bytes(b'texture fixture')

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding='utf-8')

    def check(self):
        return validator.check_contract(self.stage, self.base, validator.DEFAULT_BINDINGS)

    def test_complete_contract_is_only_structural_evidence(self):
        library, result = self.check()
        self.assertEqual(library.walk_spec.cycle_seconds, 1.8)
        self.assertNotEqual(result['moc_sha256'], result['baseline_moc_sha256'])
        self.assertNotIn('status', result)
        self.assertEqual(result['new_pose_parts'], ['WalkingLeft', 'WalkingRight'])

    def test_old_moc_cannot_pass_as_new_walking_export(self):
        (self.stage / 'model.moc3').write_bytes((self.base / 'model.moc3').read_bytes())
        with self.assertRaisesRegex(ValueError, 'equals lift baseline'):
            self.check()

    def test_explicit_single_direction_does_not_advertise_complete_walk(self):
        del self.mapping['walk']
        self.write(self.stage / 'action-map.json', self.mapping)
        model = validator.read_json(self.stage / 'model.json')
        del model['FileReferences']['Motions']['WalkRight']
        self.write(self.stage / 'model.json', model)
        (self.stage / 'walk-right.json').unlink()
        library, result = validator.check_contract(self.stage, self.base, validator.DEFAULT_BINDINGS,
                                                  directions=('left',))
        self.assertIsNone(library.walk_spec)
        self.assertNotIn('walk', library.mapping)
        self.assertFalse(result['complete_walk_capability_declared'])
        self.assertFalse(result['both_directions_checked'])
        self.assertEqual(result['directions_checked'], ['left'])
        self.assertEqual(library.sample('walk-left', .9)[0]['ParamWalkHipL'], 1)
        self.assertEqual(set(result['authored_loop_endpoints']), {'WalkLeft'})

    def test_single_direction_also_rejects_stale_native_model(self):
        del self.mapping['walk']
        self.write(self.stage / 'action-map.json', self.mapping)
        (self.stage / 'model.moc3').write_bytes((self.base / 'model.moc3').read_bytes())
        with self.assertRaisesRegex(ValueError, 'equals lift baseline'):
            validator.check_contract(self.stage, self.base, validator.DEFAULT_BINDINGS,
                                     directions=('left',))

    def test_authored_endpoint_checked_before_modulo(self):
        path = self.stage / 'walk-left.json'
        motion = validator.read_json(path)
        motion['Curves'][-1]['Segments'][-1] = .3
        self.write(path, motion)
        library = validator.MotionLibrary(self.stage)
        self.assertEqual(library.sample('walk-left', 0), library.sample('walk-left', 1.8))
        with self.assertRaisesRegex(ValueError, 'endpoint mismatch'):
            self.check()

    def test_missing_new_part_reset_in_old_inspection_motion_fails(self):
        path = self.stage / 'wave.json'
        motion = validator.read_json(path)
        motion['Curves'].pop()
        self.write(path, motion)
        with self.assertRaisesRegex(ValueError, 'omits pose tracks'):
            self.check()

    def test_visible_new_part_in_old_motion_fails(self):
        path = self.stage / 'idle.json'
        motion = validator.read_json(path)
        motion['Curves'][-1]['Segments'][1] = 1
        self.write(path, motion)
        with self.assertRaisesRegex(ValueError, 'leaves walking part'):
            self.check()

    def test_changed_old_motion_is_detected(self):
        path = self.stage / 'idle.json'
        motion = validator.read_json(path)
        motion['Curves'][0]['Segments'][1] = 1
        self.write(path, motion)
        with self.assertRaisesRegex(ValueError, 'Legacy parameter motion changed'):
            self.check()

    def test_missing_export_writes_failure_without_native_previews(self):
        out = Path(self.temp.name) / 'reports'
        with self.assertRaisesRegex(ValueError, 'No walk capability'):
            validator.main(['--stage', str(self.base), '--baseline', str(self.base), '--out', str(out)])
        reports = list(out.rglob('native-validation.json'))
        self.assertEqual(len(reports), 1)
        report = validator.read_json(reports[0])
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['viewer_checked'])
        self.assertNotIn('preview_frames', report)
        self.assertFalse(list(out.rglob('*.gif')))


class SoleContactMeasurementTests(unittest.TestCase):
    def samples(self, local_velocity, height=0):
        return [{'seconds': index/10, 'support': 1 <= index <= 7,
                 'sole_center_x_native_pixels': local_velocity*index/10,
                 'height_above_ground_native_pixels': height}
                for index in range(10)]

    def test_both_travel_directions_cancel_planted_local_motion(self):
        for direction, velocity in (('left', 68), ('right', -68)):
            segment = validator.contact_segments(self.samples(velocity), 1, direction, 68)[0]
            self.assertAlmostEqual(segment['world_anchor_slip_native_pixels'], 0)
            self.assertAlmostEqual(segment['stride_for_zero_mean_stance_slip_native_pixels'], 68)

    def test_static_local_foot_slips_when_window_moves_and_constant_hover_is_reported(self):
        segment = validator.contact_segments(self.samples(0, 2.5), 1, 'left', 68)[0]
        self.assertAlmostEqual(segment['world_anchor_slip_native_pixels'], 40.8)
        self.assertEqual(segment['max_absolute_height_native_pixels'], 2.5)
        self.assertEqual(segment['height_range_native_pixels'], 0)

    def test_partial_stances_at_capture_edges_are_not_calibration_evidence(self):
        values = self.samples(68)
        for index, value in enumerate(values):
            value['support'] = index <= 3 or index >= 6
        self.assertEqual(validator.contact_segments(values, 1, 'left', 68), [])


class NativeFloatPrecisionTests(unittest.TestCase):
    def test_float32_hierarchy_roundoff_is_not_visible_region_movement(self):
        self.assertTrue(validator.native_static_unchanged(1.043081283569336e-7))
        self.assertLess(validator.NATIVE_STATIC_EPSILON*384, .001)
        self.assertLess(validator.NATIVE_STATIC_EPSILON, 1e-5)

    def test_static_tolerance_includes_boundary_and_rejects_real_excess(self):
        import math
        limit = validator.NATIVE_STATIC_EPSILON
        self.assertTrue(validator.native_static_unchanged(limit))
        self.assertFalse(validator.native_static_unchanged(math.nextafter(limit, math.inf)))
        self.assertFalse(validator.native_static_unchanged(1e-5))

    def test_nonfinite_vertex_delta_never_counts_as_unchanged(self):
        self.assertFalse(validator.native_static_unchanged(float('nan')))
        self.assertFalse(validator.native_static_unchanged(float('inf')))


class MeasuredPlantCalibrationTests(unittest.TestCase):
    def test_inverse_uses_measured_sign_and_asymmetric_endpoint_amplitudes(self):
        self.assertAlmostEqual(calibrator.measured_plant_value(-5, 8, -10), .5)
        self.assertAlmostEqual(calibrator.measured_plant_value(4, 8, -10), -.5)
        self.assertAlmostEqual(calibrator.measured_plant_value(5, -8, 10), .5)
        self.assertAlmostEqual(calibrator.measured_plant_value(-4, -8, 10), -.5)

    def test_unreachable_or_unbound_translation_cannot_generate_clipped_curves(self):
        with self.assertRaisesRegex(ValueError, 'outside measured'):
            calibrator.measured_plant_value(-11, 8, -10)
        with self.assertRaisesRegex(ValueError, 'opposite directions'):
            calibrator.measured_plant_value(2, 0, 0)

    def test_calibration_is_tied_to_both_moc_and_authored_gait(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'fixture.moc3').write_bytes(b'unit fixture only, no native loading')
            motion = preparer.make_motion('left', {'StandingSet', 'WalkingLeftSet'}, 1.8)
            data = {'status': 'native_measured_candidate', 'direction': 'left',
                    'mocSha256': hashlib.sha256((root/'fixture.moc3').read_bytes()).hexdigest(),
                    'motionSignatureSha256': preparer.motion_signature(motion),
                    'curves': [{'Target': 'Parameter', 'Id': key, 'Segments': [0, .2, 0, 1.8, .2]}
                               for key in preparer.PLANT_PARAMS]}
            path = root/'calibration.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            exported = {'FileReferences': {'Moc': 'fixture.moc3'}}
            self.assertEqual(len(preparer.calibrated_plant_curves(path, root, exported, 'left', motion)), 2)
            changed = copy.deepcopy(motion)
            changed['Curves'][0]['Segments'][1] += .01
            with self.assertRaisesRegex(ValueError, 'gait changed'):
                preparer.calibrated_plant_curves(path, root, exported, 'left', changed)
            (root/'fixture.moc3').write_bytes(b'another unit fixture')
            with self.assertRaisesRegex(ValueError, 'different MOC'):
                preparer.calibrated_plant_curves(path, root, exported, 'left', motion)


class BidirectionalPlantCalibrationTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'fixture.moc3').write_bytes(b'unit fixture only, never native-loaded')
        self.digest = hashlib.sha256((self.root/'fixture.moc3').read_bytes()).hexdigest()
        self.exported = {'FileReferences': {'Moc': 'fixture.moc3'}}
        self.paths = {}
        for direction, value in (('left', .2), ('right', -.3)):
            data = {'status': 'native_measured_candidate', 'direction': direction, 'mocSha256': self.digest,
                    'motionSignatureSha256': preparer.motion_signature(preparer.make_motion(direction, set(), 1.8)),
                    'curves': [{'Target': 'Parameter', 'Id': key, 'Segments': [0, value, 0, 1.8, value]}
                               for key in preparer.PLANT_PARAMS]}
            path = self.root/(direction+'.json')
            path.write_text(json.dumps(data), encoding='utf-8')
            self.paths[direction] = path

    def test_two_directions_keep_distinct_measured_values_and_old_single_input_works(self):
        paths, curves = preparer.plant_calibration_set(list(self.paths.values()), ('left', 'right'),
                                                       self.root, self.exported, 1.8)
        self.assertEqual(set(paths), {'left', 'right'})
        self.assertEqual(curves['left'][0]['Segments'][1], .2)
        self.assertEqual(curves['right'][0]['Segments'][1], -.3)
        paths, _ = preparer.plant_calibration_set(self.paths['left'], ('left',), self.root, self.exported, 1.8)
        self.assertEqual(set(paths), {'left'})

    def test_missing_wrong_or_duplicate_direction_is_rejected(self):
        for inputs, requested in (([self.paths['left']], ('left', 'right')),
                                  ([self.paths['left']], ('right',)),
                                  ([self.paths['left'], self.paths['left']], ('left', 'right'))):
            with self.subTest(inputs=inputs, requested=requested), self.assertRaises(ValueError):
                preparer.plant_calibration_set(inputs, requested, self.root, self.exported, 1.8)

    def test_one_stale_moc_or_changed_gait_rejects_the_entire_pair(self):
        path = self.paths['right']
        data = json.loads(path.read_text(encoding='utf-8'))
        data['mocSha256'] = 'old-export'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different MOC'):
            preparer.plant_calibration_set(list(self.paths.values()), ('left', 'right'),
                                           self.root, self.exported, 1.8)
        data['mocSha256'] = self.digest
        data['motionSignatureSha256'] = 'old-gait'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'gait changed'):
            preparer.plant_calibration_set(list(self.paths.values()), ('left', 'right'),
                                           self.root, self.exported, 1.8)


class ExportStructureFallbackTests(unittest.TestCase):
    def test_valid_display_info_uses_cheap_structure_check(self):
        data = {'Parameters': [{'Id': key} for key in preparer.PARAMS],
                'Parts': [{'Id': 'WalkingLeftSet'}]}
        model = {'FileReferences': {'DisplayInfo': 'display.cdi3.json'}}
        with patch.object(preparer, 'read', return_value=data), patch.object(preparer, 'native_export_ids') as native:
            ids, parts, source = preparer.export_structure(ROOT, model, {'WalkingLeftSet'})
        native.assert_not_called()
        self.assertEqual(source, 'DisplayInfo')
        self.assertEqual(ids, set(preparer.PARAMS))
        self.assertEqual(parts, {'WalkingLeftSet'})

    def test_missing_optional_display_info_reads_actual_native_ids(self):
        model = {'FileReferences': {'DisplayInfo': 'absent-display.cdi3.json'}}
        actual = (set(preparer.PARAMS), {'WalkingLeftSet', 'WalkingRightSet'})
        with patch.object(preparer, 'read', side_effect=FileNotFoundError), \
                patch.object(preparer, 'native_export_ids', return_value=actual) as native:
            ids, parts, source = preparer.export_structure(ROOT, model, {'WalkingLeftSet'})
        native.assert_called_once_with(ROOT, model)
        self.assertEqual((ids, parts), actual)
        self.assertEqual(source, 'actual_native_moc')
        self.assertNotIn('DisplayInfo', model['FileReferences'])

    def test_stale_display_info_never_substitutes_for_actual_native_structure(self):
        stale = {'Parameters': [{'Id': 'OldDisplayParameter'}], 'Parts': [{'Id': 'StandingSet'}]}
        model = {'FileReferences': {'DisplayInfo': 'stale.cdi3.json'}}
        actual = ({'ActualNativeParameter'}, {'WalkingLeftSet'})
        with patch.object(preparer, 'read', return_value=stale), \
                patch.object(preparer, 'native_export_ids', return_value=actual):
            ids, parts, source = preparer.export_structure(ROOT, model, {'WalkingLeftSet'})
        self.assertEqual((ids, parts), actual)
        self.assertNotIn('OldDisplayParameter', ids)
        self.assertEqual(source, 'actual_native_moc')
        self.assertNotIn('DisplayInfo', model['FileReferences'])

    def test_missing_old_atlas_still_blocks_before_any_metadata_fallback_or_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base, out = Path(temp)/'baseline', Path(temp)/'candidate'
            base.mkdir(); out.mkdir()
            (base/'action-map.json').write_text(json.dumps({'model': 'base.model3.json'}), encoding='utf-8')
            (base/'base.model3.json').write_text(json.dumps({'FileReferences': {}}), encoding='utf-8')
            original = json.dumps({'FileReferences': {'Moc': 'model.moc3', 'Textures': ['missing-old-atlas.png']}})
            (out/'model.model3.json').write_text(original, encoding='utf-8')
            (out/'model.moc3').write_bytes(b'unit fixture only; never native-loaded')
            with patch.object(preparer, 'native_export_ids') as native:
                with self.assertRaisesRegex(ValueError, 'Missing exported asset: missing-old-atlas'):
                    preparer.prepare(base, out, 'model', ('left',), 1.8, 68)
            native.assert_not_called()
            self.assertEqual((out/'model.model3.json').read_text(encoding='utf-8'), original)
            self.assertFalse((out/'action-map.json').exists())


if __name__ == '__main__':
    unittest.main()
