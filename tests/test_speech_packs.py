import json
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile

from deskpet.speech.config import speech_paths
from deskpet.speech.packs import PACK_FOLDER, pack_config


class Settings(dict):
    value = dict.get


class PackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / PACK_FOLDER
        self.folder.mkdir()
        self.audio = self.root / 'ref.wav'
        with wave.open(str(self.audio), 'wb') as w:
            w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            w.writeframes(b'\0\0' * 48000)

    def create(self, name, gpt=b'original', manifest=True):
        path = self.folder / name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('nested/weights/gpt.ckpt', gpt)
            z.writestr('nested/weights/speaker.pth', b'05acoustic')
            z.write(self.audio, 'nested/ref.wav')
            z.writestr('nested/prompt.txt', '你好呀。')
            if manifest:
                z.writestr('nested/voice.json', json.dumps(
                    dict(format=1, version='v2Pro', gpt='weights/gpt.ckpt', sovits='weights/speaker.pth',
                         reference='ref.wav', text='你好呀。', python='untrusted.exe')))
        return path

    def unpack(self, path):
        return pack_config(path, self.root/'engine', self.root/'cache')

    def test_first_pack_and_saved_selection(self):
        c = self.create('C.zip')
        a = self.create('A.zip')
        self.assertEqual(speech_paths(Settings(), self.root, self.root)[2], str(a))
        self.assertEqual(speech_paths(Settings({'speech/config':str(c)}), self.root, self.root)[2], str(c))

    def test_manifest_cache_and_replaced_zip(self):
        path = self.create('same.zip')
        first = self.unpack(path)
        self.assertNotIn('python', first)
        self.assertEqual(first['reference']['text'], '你好呀。')
        self.assertEqual(first, self.unpack(path))
        self.create('same.zip', gpt=b'updated')
        second = self.unpack(path)
        self.assertNotEqual(first['reference']['audio'], second['reference']['audio'])
        self.assertEqual(Path(second['model']['t2s_weights_path']).read_bytes(), b'updated')

    def test_simple_legacy_pack_and_unsafe_member(self):
        path = self.create('C.zip', manifest=False)
        self.assertEqual(self.unpack(path)['model']['version'], 'v2Pro')
        with zipfile.ZipFile(path, 'a') as z:
            z.writestr('../escape.txt', 'invalid')
        with self.assertRaises(ValueError):
            self.unpack(path)
        self.assertFalse((self.root/'escape.txt').exists())

    def test_settings_refresh_selects_new_pack(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QPushButton
        from deskpet.speech.settings import settings_dialog
        app = QApplication.instance() or QApplication([])
        a = self.create('A.zip')
        c = self.folder/'C.zip'
        def choose():
            dialog = app.activeModalWidget()
            selector = dialog.findChild(QComboBox)
            self.create('C.zip')
            next(b for b in dialog.findChildren(QPushButton) if b.text() == '刷新').click()
            selector.setCurrentIndex(selector.findData(str(c)))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
        QTimer.singleShot(0, choose)
        result = settings_dialog(None, (str(self.audio), str(self.root), str(a)), packs_dir=self.folder)
        self.assertEqual(result[2], str(c))
