import json
from pathlib import Path
import tempfile
import unittest
from PySide6.QtGui import QImage
from deskpet.pet.characters import read_pack, validate_images, builtin_sources, discover_packs, selected_folder


class CharacterPackTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / 'pet'
        self.root.mkdir()
        self.image(self.root / 'idle.png')
        self.data = {'version': 1, 'id': 'my-pet', 'name': '测试角色', 'states': {'idle': 'idle.png'}}

    def image(self, path, width=16, alpha=True):
        image = QImage(width, 16, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
        image.fill(0 if alpha else 0xffffffff)
        if alpha:
            image.setPixelColor(width // 2, 8, 0xffffffff)
        assert image.save(str(path))

    def load(self):
        (self.root / 'character.json').write_text(json.dumps(self.data), encoding='utf-8')
        return read_pack(self.root)

    def test_minimal_pack_and_optional_state_fallback(self):
        pack = self.load()
        validate_images(pack)
        self.assertEqual(pack.state_path('sleep'), self.root / 'idle.png')
        self.assertEqual(pack.anchors['head'], (0.5, 0.28))
        self.assertIsNone(pack.singing_hem)

    def test_explicit_singing_legs_and_custom_hem_keep_front_fallback(self):
        self.image(self.root / 'sing-front.png')
        self.data['states']['sing-front'] = 'sing-front.png'
        self.data['singing_motion'] = {'legs': True, 'hem': 0.7}
        pack = self.load()
        self.assertEqual(pack.singing_hem, 0.7)
        self.assertEqual(pack.state_path('sing-left'), self.root / 'sing-front.png')
        self.data['singing_motion'] = {'legs': True}
        self.assertEqual(self.load().singing_hem, 0.64)

    def test_optional_work_poses_and_wait_fallback(self):
        self.image(self.root / 'work.png')
        self.data['states']['work'] = 'work.png'
        pack = self.load()
        self.assertEqual(pack.state_path('work-wait'), self.root / 'work.png')
        self.assertEqual(set(validate_images(pack)), {'idle', 'work'})
        self.image(self.root / 'work-wait.png')
        self.data['states']['work-wait'] = 'work-wait.png'
        self.assertEqual(self.load().state_path('work-wait'), self.root / 'work-wait.png')
        del self.data['states']['work']
        with self.assertRaisesRegex(ValueError, '需要提供 work'):
            self.load()

    def test_work_poses_inferred_without_manifest(self):
        self.image(self.root / 'work.png')
        self.image(self.root / 'work-wait.png')
        pack = read_pack(self.root)
        self.assertEqual(set(pack.states), {'idle', 'work', 'work-wait'})

    def test_top_level_work_poses_preserve_legacy_state_names(self):
        self.image(self.root / 'work.png')
        self.data['work_poses'] = {'work': 'work.png'}
        pack = self.load()
        self.assertEqual(set(self.data['states']), {'idle'})
        self.assertEqual(set(pack.states), {'idle', 'work'})
        for value in (None, [], {'idle': 'idle.png'}, {'work-wait': 'work.png'}):
            self.data['work_poses'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()
        self.data['work_poses'] = {'work': '../outside.png'}
        with self.assertRaises(ValueError):
            self.load()
        self.data['work_poses'] = {'work': 'work.png'}
        self.data['states']['work'] = 'work.png'
        with self.assertRaisesRegex(ValueError, '重复'):
            self.load()

    def test_per_pose_heads_and_fallback_keep_idle_anchor(self):
        self.image(self.root / 'work.png')
        self.data['states']['work'] = 'work.png'
        self.data['pose_heads'] = {'work': [.4, .6]}
        pack = self.load()
        self.assertEqual(pack.head_for('work'), (.4, .6))
        self.assertEqual(pack.head_for('work-wait'), (.4, .6))
        self.assertEqual(pack.head_for('idle'), (.5, .28))
        for value in (None, [], {'missing': [.5, .5]}, {'work': [True, .5]},
                      {'work': [.5]}, {'work': [.5, float('nan')]}, {'work': [1.1, .5]},
                      {'work': [10 ** 400, .5]}):
            self.data['pose_heads'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_disabled_singing_keeps_old_pack_behavior(self):
        for value in ({}, {'legs': False}, {'hem': 0.65}, {'legs': False, 'hem': 0.65}):
            self.data['singing_motion'] = value
            with self.subTest(value=value):
                self.assertIsNone(self.load().singing_hem)

    def test_enabled_singing_requires_authored_front_frame(self):
        self.data['singing_motion'] = {'legs': True}
        with self.assertRaisesRegex(ValueError, 'sing-front'):
            self.load()

    def test_singing_rejects_invalid_config(self):
        self.image(self.root / 'sing-front.png')
        self.data['states']['sing-front'] = 'sing-front.png'
        for value in (None, True, [], {'extra': True}, {'legs': 1}, {'legs': 'true'},
                      {'hem': True}, {'hem': '0.65'}, {'hem': float('nan')},
                      {'hem': float('inf')}, {'hem': -float('inf')},
                      {'hem': 10 ** 400}, {'hem': -(10 ** 400)},
                      {'hem': 0.34}, {'hem': 0.91}):
            self.data['singing_motion'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_rejects_external_paths(self):
        self.image(self.root.parent / 'outside.png')
        for path in ('../outside.png', str((self.root.parent / 'outside.png').resolve())):
            self.data['states']['idle'] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.load()

    def test_rejects_external_symlink(self):
        self.image(self.root.parent / 'outside.png')
        try:
            (self.root / 'link.png').symlink_to(self.root.parent / 'outside.png')
        except OSError:
            self.skipTest('symlink creation unavailable')
        self.data['states']['idle'] = 'link.png'
        with self.assertRaises(ValueError):
            self.load()

    def test_missing_idle_and_bad_schema(self):
        for changes in ({'states': {}}, {'version': True}, {'version': 2}, {'id': '../pet'},
                        {'name': ''}, {'states': {'idle': 'missing.png'}}):
            original = self.data.copy()
            self.data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.load()
            self.data = original

    def test_anchor_validation(self):
        for pair in ([1.1, 0], [0, float('nan')], [True, 0], [0], 'head'):
            self.data['anchors'] = {'head': pair}
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                self.load()
        self.data['anchors'] = {'head': [0.4, 0.2]}
        self.assertEqual(self.load().anchors['head'], (0.4, 0.2))

    def test_rejects_mismatched_canvas_and_opaque_format(self):
        self.image(self.root / 'blink.png', width=20)
        self.data['states']['blink'] = 'blink.png'
        with self.assertRaises(ValueError):
            validate_images(self.load())
        self.data['states'].pop('blink')
        self.image(self.root / 'idle.png', alpha=False)
        with self.assertRaises(ValueError):
            validate_images(self.load())

    def test_rejects_corrupt_png(self):
        (self.root / 'idle.png').write_bytes(b'not a png')
        with self.assertRaises(ValueError):
            validate_images(self.load())

    def test_builtins_keep_current_state_files(self):
        self.assertEqual(builtin_sources('refined')['sleep'].name, 'sleep-back.png')
        self.assertEqual(builtin_sources('simple'), builtin_sources('refined'))

    def test_png_only_folder_needs_no_manifest(self):
        pack = read_pack(self.root)
        self.assertEqual(pack.name, 'pet')
        self.assertEqual(pack.states, {'idle': self.root / 'idle.png'})
        validate_images(pack)

    def test_side_singing_falls_back_to_front(self):
        self.image(self.root / 'sing-front.png')
        self.data['states']['sing-front'] = 'sing-front.png'
        pack = self.load()
        self.assertEqual(pack.state_path('sing-left'), self.root / 'sing-front.png')
        self.assertEqual(pack.state_path('sleep'), self.root / 'idle.png')

    def test_discovery_isolates_invalid_pack_without_decoding_images(self):
        bad = self.root.parent / 'bad'
        bad.mkdir()
        (bad / 'character.json').write_text('{broken', encoding='utf-8')
        # Metadata scanning is intentionally lazy; decoding happens on selection.
        (self.root / 'idle.png').write_bytes(b'bad PNG')
        packs, errors = discover_packs(self.root.parent)
        self.assertIn('external:pet', packs)
        self.assertEqual(len(errors), 1)
        with self.assertRaises(ValueError):
            validate_images(packs['external:pet'])

    def test_selection_cannot_escape_root(self):
        for value in ('external:../pet', 'external:C:pet', 'external:', 'refined'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                selected_folder(self.root.parent, value)

    def test_blank_and_fully_opaque_rgba_are_rejected(self):
        for fill in (0, 0xffffffff):
            image = QImage(16, 16, QImage.Format.Format_ARGB32)
            image.fill(fill)
            image.save(str(self.root / 'idle.png'))
            with self.subTest(fill=fill), self.assertRaises(ValueError):
                validate_images(read_pack(self.root))

    def test_head_must_be_above_feet(self):
        self.data['anchors'] = {'head': [.5, .9], 'feet': [.5, .8]}
        with self.assertRaises(ValueError):
            self.load()
