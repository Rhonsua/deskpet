"""Appearance upgrade policy must not erase subsequent user choices."""
import tempfile
from pathlib import Path
import unittest
from PySide6.QtCore import QSettings
from visual_style import APPEARANCE_REVISION, preferred_variant


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        output = Path(__file__).resolve().parents[1] / 'preview' / 'appearance'
        output.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix='test-', dir=output)
        self.addCleanup(scratch.cleanup)
        self.settings = QSettings(str(Path(scratch.name) / 'prefs.ini'), QSettings.Format.IniFormat)

    def test_new_install_defaults_to_live2d(self):
        self.assertEqual(preferred_variant(self.settings), 'live2d')

    def test_existing_builtin_moves_to_live2d_once(self):
        self.settings.setValue('appearance_revision', 'refined-smooth-v1')
        self.settings.setValue('character_selection', 'refined')
        self.assertEqual(preferred_variant(self.settings), 'live2d')
        self.settings.setValue('appearance_revision', APPEARANCE_REVISION)
        self.settings.setValue('character_selection', 'simple')
        self.settings.sync()
        reopened = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        self.assertEqual(preferred_variant(reopened), 'simple')

    def test_upgrade_preserves_custom_character(self):
        self.settings.setValue('character_selection', 'external:my-character')
        self.assertEqual(preferred_variant(self.settings), 'external:my-character')


if __name__ == '__main__':
    unittest.main()
