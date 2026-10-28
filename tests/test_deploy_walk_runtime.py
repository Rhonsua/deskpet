"""Deployment guard tests only; never apply against production assets."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'experiments/live2d-tianyi/deploy_walk_runtime.py'
if not SCRIPT.is_file():
    raise unittest.SkipTest('Local Cubism deployment tools are not part of the code-only checkout')
SPEC = importlib.util.spec_from_file_location(
    'deploy_walk_runtime_for_tests', SCRIPT)
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class WalkDeploymentGuardTests(unittest.TestCase):
    def native_prefix(self):
        return {'status': 'passed_native_checks_pending_visual_acceptance', 'both_directions_checked': True,
                'directions_checked': ['left', 'right'], 'unfinishedBindings': [], 'moc_sha256': 'unit-digest'}

    def test_single_direction_or_unfinished_report_cannot_authorize_deployment(self):
        report = self.native_prefix()
        report['both_directions_checked'] = False
        with self.assertRaisesRegex(ValueError, 'complete two-direction'):
            deploy.native_accepted(report, 'unit-digest')
        report = self.native_prefix()
        report['unfinishedBindings'] = ['ParamWalkBounce']
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            deploy.native_accepted(report, 'unit-digest')

    def test_old_moc_and_unaccepted_or_stale_visual_record_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            deploy.native_accepted(self.native_prefix(), 'another-export')
        with self.assertRaisesRegex(ValueError, 'unaccepted'):
            deploy.visual_accepted({'accepted': False}, {}, 'current-set', 'unit-digest')
        with self.assertRaisesRegex(ValueError, 'hashes do not match'):
            deploy.visual_accepted({'accepted': True, 'directions': ['left', 'right'],
                                    'assets_sha256': 'old-set', 'files_sha256': {}},
                                   {}, 'current-set', 'unit-digest')

    def test_path_traversal_absolute_paths_and_drive_relative_paths_are_rejected(self):
        for value in ('../escape.moc3', 'models/../../escape.moc3', '/absolute.png',
                      'C:\\outside.png', 'C:drive-relative.png', '\\\\server\\share\\model.moc3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                deploy.local(ROOT, value)
        self.assertEqual(deploy.local(ROOT, 'walk/hash/texture.png'), ROOT/'walk/hash/texture.png')

    def test_mapping_change_cancels_apply_before_any_staging_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            mapping = target/'action-map.json'
            mapping.write_bytes(b'newer-runtime-selection')
            with self.assertRaisesRegex(ValueError, 'changed after dry-run'):
                deploy.apply_plan({'target': target, 'source': target, 'previous_bytes': b'old-selection'})
            self.assertEqual(mapping.read_bytes(), b'newer-runtime-selection')
            self.assertEqual(list(target.iterdir()), [mapping])

    def test_revoked_review_cancels_apply_before_any_staging_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            mapping, native, visual = [target/name for name in ('action-map.json', 'native.json', 'visual.json')]
            mapping.write_bytes(b'old-selection')
            native.write_bytes(b'unchanged-unit-record')
            visual.write_bytes(b'revoked-unit-record')
            plan = {'target': target, 'source': target, 'previous_bytes': b'old-selection',
                    'native_path': native, 'native_bytes': b'unchanged-unit-record',
                    'visual_path': visual, 'visual_bytes': b'earlier-unit-record'}
            with self.assertRaisesRegex(ValueError, 'records changed'):
                deploy.apply_plan(plan)
            self.assertEqual(mapping.read_bytes(), b'old-selection')
            self.assertEqual(len(list(target.iterdir())), 3)


if __name__ == '__main__':
    unittest.main()
