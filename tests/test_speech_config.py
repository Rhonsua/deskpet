import json
from pathlib import Path
import tempfile
import unittest

from deskpet.speech.config import speech_paths, speech_volume, installation_status, missing_paths


class Settings:
    def __init__(self, **values): self.values = values
    def value(self, key, default=None): return self.values.get(key, default)


class SpeechConfigTests(unittest.TestCase):
    def test_manifest_discovery_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / 'local-work' / 'tianyi-tts'
            base.mkdir(parents=True)
            config = base / 'speech-config.json'
            config.write_text(json.dumps({'python': 'runtime/python.exe', 'engine_root': 'engine'}), encoding='utf-8-sig')
            paths = speech_paths(Settings(), folder)
            self.assertEqual(paths, (str(base / 'runtime/python.exe'), str(base / 'engine'), str(config)))
            paths = speech_paths(Settings(**{'speech/python': 'chosen.exe', 'speech/engine': ''}), folder)
            self.assertEqual(paths[:2], ('chosen.exe', str(base / 'engine')))

    def test_custom_manifest_and_broken_json_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            custom = Path(folder) / 'custom.json'
            custom.write_text('{broken', encoding='utf-8')
            paths = speech_paths(Settings(**{'speech/config': str(custom)}), folder)
            self.assertEqual(paths[2], str(custom))
            self.assertEqual(paths[0], str(Path(folder) / 'local-work/tianyi-tts/runtime/Scripts/python.exe'))
            self.assertIn('尚未找到', installation_status(paths))
            custom.write_text(json.dumps({'python': 3, 'engine_root': []}), encoding='utf-8')
            self.assertEqual(speech_paths(Settings(**{'speech/config': str(custom)}), folder), paths)

    def test_empty_engine_is_missing_even_when_current_directory_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'file'
            file.touch()
            for blank in ('', '   '):
                paths = (str(file), blank, str(file))
                self.assertEqual(missing_paths(paths), ['语音引擎'])
                self.assertIn('尚未找到：语音引擎', installation_status(paths))

    def test_dialog_rejects_blank_engine_with_matching_warning(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QLineEdit, QDialogButtonBox
        from PySide6.QtCore import QTimer
        from deskpet.speech.settings import settings_dialog
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'file'
            file.touch()
            paths = (str(file), folder, str(file))
            rejected = []
            def try_save():
                dialog = app.activeModalWidget()
                next(edit for edit in dialog.findChildren(QLineEdit) if edit.text() == folder).setText('   ')
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                rejected.append(dialog.isVisible())
                dialog.reject()
            with patch('deskpet.speech.settings.QMessageBox.warning') as warning:
                QTimer.singleShot(0, try_save)
                self.assertIsNone(settings_dialog(None, paths))
            self.assertEqual(rejected, [True])
            self.assertEqual(warning.call_count, 1)
            self.assertEqual(warning.call_args.args[2], installation_status((str(file), '', str(file))))

    def test_volume_is_bounded_and_invalid_values_recover(self):
        for value, expected in ((150, 100), (-1, 0), ('25', 25), ('bad', 100), (None, 100)):
            self.assertEqual(speech_volume(Settings(**{'speech/volume': value})), expected)


if __name__ == '__main__': unittest.main()
