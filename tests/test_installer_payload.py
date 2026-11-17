"""Isolated native compression/install checks; no user registry or shortcuts."""
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer_payload', ROOT / 'packaging/installer_payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


@unittest.skipUnless(os.name == 'nt', 'Windows native installer')
class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'local-work' / 'reports'
        parent.mkdir(parents=True, exist_ok=True)
        cls.scratch = tempfile.TemporaryDirectory(prefix='payload-test-', dir=parent)
        cls.root = Path(cls.scratch.name)
        source = cls.root / 'Setup.cs'
        source.write_text((ROOT / 'packaging/Setup.cs').read_text(encoding='utf-8').replace('__APP_VERSION__', '0.0.0'), encoding='utf-8-sig')
        cls.setup = cls.root / 'Setup.exe'
        compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64',
            '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
            '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
            '/out:' + str(cls.setup), str(source), str(ROOT / 'packaging/InstallerPayload.cs')],
            check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='case-', dir=self.root)
        self.folder = Path(self.scratch.name)
        self.install = self.folder / 'installed'
        self.extracted = self.folder / 'extracted'
        self.extracted.mkdir()
        self.exe = self.extracted / 'Setup.exe'
        self.exe.write_bytes(self.setup.read_bytes())
        self.temp = self.folder / 'temp'
        self.temp.mkdir()
        self.environment = dict(os.environ, TEMP=str(self.temp), TMP=str(self.temp))
        self.raw, self.packed = self.extracted / 'payload.zip', self.extracted / 'payload.tlz'

    def tearDown(self):
        self.scratch.cleanup()

    def prepare(self, *, compressed=True, malicious=False):
        with zipfile.ZipFile(self.raw, 'w', zipfile.ZIP_STORED) as archive:
            archive.writestr('TianyiPet.exe', b'test placeholder')
            archive.writestr('中文文件夹/素材.bin', os.urandom(2300000))
            archive.writestr('VERSION.txt', '0.0.0\n')
            if malicious:
                archive.writestr('../outside.txt', 'must not extract')
        self.raw_hash = payload.digest(self.raw)
        if compressed:
            # Three small native blocks exercise streaming without a big test.
            with patch.object(payload, 'BLOCK_SIZE', 1024 * 1024):
                payload.compress(self.raw, self.packed)
            self.raw.unlink()

    def run_setup(self, *extra):
        result = subprocess.run([str(self.exe), '--quiet', '--test', '--dir', str(self.install), *extra],
            env=self.environment, capture_output=True, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(list(self.temp.glob('TianyiPayload-*.zip')), [], 'decoded temporary ZIP leaked')
        return result.returncode

    def test_python_and_csharp_roundtrip_legacy_and_uninstall_keep_user_file(self):
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                self.prepare(compressed=compressed)
                if compressed:
                    decoded = self.folder / 'decoded.zip'
                    payload.decompress(self.packed, decoded)
                    self.assertEqual(payload.digest(decoded), self.raw_hash)
                    decoded.unlink()
                self.assertEqual(self.run_setup(), 0)
                self.assertTrue((self.install / '中文文件夹/素材.bin').is_file())
                keep = self.install / 'user-file.txt'
                keep.write_text('keep me')
                self.assertEqual(self.run_setup('--uninstall'), 0)
                self.assertEqual(list(self.install.iterdir()), [keep])
                keep.unlink()
                self.install.rmdir()

    def test_corrupt_payload_fails_before_old_manifest_or_files_change(self):
        self.prepare()
        self.install.mkdir()
        existing = self.install / 'installed-files.txt'
        existing.write_bytes(b'previous manifest')
        content = self.packed.read_bytes()
        variants = [b'wrong!!!' + content[8:], content[:16] + bytes(32) + content[48:],
                    content[:52] + struct.pack('<I', 0xffffffff) + content[56:], content[:-10], content + b'trailing']
        for data in variants:
            with self.subTest(prefix=data[:16]):
                self.packed.write_bytes(data)
                self.assertNotEqual(self.run_setup(), 0)
                self.assertEqual(existing.read_bytes(), b'previous manifest')
                self.assertEqual(list(self.install.iterdir()), [existing])

    def test_path_escape_still_rejected(self):
        self.prepare(malicious=True)
        self.assertNotEqual(self.run_setup(), 0)
        self.assertFalse((self.folder / 'outside.txt').exists())

    def test_python_decoder_does_not_replace_existing_target_on_failure(self):
        self.prepare()
        target = self.folder / 'keep'
        target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            payload.decompress(self.packed, target)
        self.assertEqual(target.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
