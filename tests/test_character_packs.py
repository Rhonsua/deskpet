import json
from pathlib import Path
import tempfile
import unittest
from PySide6.QtGui import QImage
from character_packs import read_pack, validate_images, builtin_sources


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
        assert image.save(str(path))

    def load(self):
        (self.root / 'character.json').write_text(json.dumps(self.data), encoding='utf-8')
        return read_pack(self.root)

    def test_minimal_pack_and_optional_state_fallback(self):
        pack = self.load()
        validate_images(pack)
        self.assertEqual(pack.state_path('sleep'), self.root / 'idle.png')
        self.assertEqual(pack.anchors['head'], (0.5, 0.28))

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
        self.assertEqual(len(builtin_sources('simple')), 1)
