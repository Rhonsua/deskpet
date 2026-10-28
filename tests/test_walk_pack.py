"""Optional walk sequences share canvas, anchor and allocation rules with poses."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage

from character_packs import read_pack, validate_images, validate_walk_images


class WalkPackTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        for name in ('idle', 'left0', 'left1', 'right0', 'right1'):
            self.image(name)
        self.data = {'version': 1, 'id': 'walker', 'name': 'Walker',
                     'states': {'idle': 'idle.png'},
                     'walk': {'left': ['left0.png', 'left1.png'],
                              'right': ['right0.png', 'right1.png'],
                              'fps': 4, 'stride': 32}}

    def image(self, name, width=16):
        image = QImage(width, 16, QImage.Format.Format_ARGB32)
        image.fill(0)
        image.setPixelColor(width // 2, 8, 0xffffffff)
        assert image.save(str(self.root / (name + '.png')))

    def load(self):
        (self.root / 'character.json').write_text(json.dumps(self.data), encoding='utf-8')
        return read_pack(self.root)

    def test_old_pack_has_no_walk_and_no_implicit_idle_slide(self):
        self.data.pop('walk')
        pack = self.load()
        self.assertIsNone(pack.walk)
        self.assertEqual(set(validate_images(pack)), {'idle'})
        self.assertEqual(validate_walk_images(None), {})

    def test_sequence_metadata_and_frame_sampling(self):
        pack = self.load()
        self.assertEqual(pack.walk.cycle_seconds, .5)
        self.assertEqual(pack.walk.stride, 32)
        self.assertEqual(pack.walk.frame_count, 2)
        self.assertEqual(pack.walk.frame_key(-1, 0), 'walk-left:0')
        self.assertEqual(pack.walk.frame_key('right', .25), 'walk-right:1')
        self.assertEqual(pack.walk.frame_key(1, .5), 'walk-right:0')
        self.assertEqual(pack.walk.frame_key(-1, -2), 'walk-left:0')
        frames = validate_images(pack)
        self.assertEqual(set(frames), {'idle', 'walk-left:0', 'walk-left:1',
                                      'walk-right:0', 'walk-right:1'})
        self.assertEqual(len(validate_walk_images(pack.walk)), 4)

    def test_rejects_invalid_loop_metadata(self):
        original = self.data['walk']
        cases = [None, {}, [], {'extra': 1}]
        for key in ('fps', 'stride'):
            for value in (True, '4', 0, -1, float('nan'), float('inf'), 10 ** 400):
                cases.append(dict(original, **{key: value}))
        cases.extend([dict(original, fps=31), dict(original, stride=4097),
                      dict(original, left=['left0.png']),
                      dict(original, left=['left0.png'] * 2),
                      dict(original, left=['left0.png', 'left1.png'] * 25),
                      dict(original, left=['left0.png', 'left1.png', 'left0.png']),
                      dict(original, right='right0.png')])
        for value in cases:
            self.data['walk'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load()

    def test_declared_frames_must_be_local_existing_png(self):
        for name in ('../outside.png', str((self.root / 'left0.png').resolve()),
                     'missing.png', 'idle.jpg'):
            self.data['walk']['left'] = [name, 'left1.png']
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load()

    def test_walk_frames_share_pose_canvas_and_alpha_rules(self):
        self.image('left1', width=20)
        pack = self.load()
        with self.assertRaisesRegex(ValueError, '画布尺寸'):
            validate_images(pack)
        with self.assertRaisesRegex(ValueError, '画布尺寸'):
            validate_walk_images(pack.walk)
        self.image('left1')
        (self.root / 'left1.png').write_bytes(b'bad PNG')
        with self.assertRaisesRegex(ValueError, 'PNG'):
            validate_images(pack)

    def test_pose_and_sequence_share_one_decoded_pixel_budget(self):
        # Header-only mock tests budget accounting without allocating huge images.
        from PySide6.QtCore import QSize
        pack = self.load()

        class Reader:
            def __init__(self, path):
                self.path = Path(path)

            def size(self):
                return QSize(2048, 2048)

            def format(self):
                return b'png'

            def read(self):
                return QImage(str(self.path))

        with patch('PySide6.QtGui.QImageReader', Reader):
            with self.assertRaisesRegex(ValueError, '1600 万像素'):
                validate_images(pack)
            self.assertEqual(len(validate_walk_images(pack.walk)), 4)

    def test_repeated_loop_frames_are_decoded_once(self):
        original = self.data['walk']['left']
        self.data['walk']['left'] = original * 2
        self.data['walk']['right'] *= 2
        images = validate_images(self.load())
        self.assertIs(images['walk-left:0'], images['walk-left:2'])


if __name__ == '__main__':
    unittest.main()
