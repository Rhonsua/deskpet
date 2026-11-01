"""Setup ordering, cancellation, integrity and update-safe storage regressions."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

from deskpet.chat import harness_bootstrap as setup
from deskpet.chat.harness_runtime import VERSION, runtime_directory, runtime_launch_args


def fixture(install, ready=False):
    files = {
        'node/node.exe': 'node',
        'node_modules/.bin/dsh.cmd': 'shim',
        'node_modules/@deepseek-ai/dsh/package.json': json.dumps({'version': VERSION}),
        'node_modules/@deepseek-ai/dsh/lib/bin.js': 'entry',
        'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js': 'approvalRequests allowed-once',
        'node_modules/@deepseek-ai/dsh-experimental-auto-review/lib/index.js': 'review',
    }
    if ready:
        files['deskpet-runtime-ready.json'] = json.dumps({'version': VERSION})
    for name, content in files.items():
        path = install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


class BootstrapTests(unittest.TestCase):
    def test_node_precedes_backend_and_marker_is_published_last(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); install = root / 'runtime'; order = []
            def node(archive, target, cancelled):
                order.append('node')
                target.mkdir(); (target / 'node.exe').write_text('node')
            def packages(stage, parent, progress, cancelled):
                self.assertEqual(order, ['node'])
                self.assertTrue((stage / 'node/node.exe').exists())
                self.assertFalse((install / 'deskpet-runtime-ready.json').exists())
                order.append('backend'); fixture(stage)
            with patch.object(setup, 'download_node', return_value=root / 'node.zip'), \
                 patch.object(setup, 'extract_node', side_effect=node), \
                 patch.object(setup, 'install_packages', side_effect=packages):
                cli = setup.ensure_runtime(install)
            self.assertEqual(order, ['node', 'backend'])
            self.assertTrue((install / 'deskpet-runtime-ready.json').is_file())
            self.assertEqual(runtime_launch_args(cli, root / 'patch')[0], str(install / 'node/node.exe'))

    def test_existing_complete_runtime_does_not_download(self):
        with tempfile.TemporaryDirectory() as folder:
            install = Path(folder) / 'runtime'; fixture(install, ready=True)
            with patch.object(setup, 'download_node') as download, patch.object(setup, 'install_packages') as npm:
                setup.ensure_runtime(install)
            download.assert_not_called(); npm.assert_not_called()

    def test_node_failure_does_not_start_npm_or_touch_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); install = root / 'runtime'; install.mkdir()
            old = install / 'original.txt'; old.write_text('old')
            session = root / 'work-sessions'; session.mkdir()
            saved = session / 'history.txt'; saved.write_text('history')
            with patch.object(setup, 'download_node', side_effect=ValueError('bad hash')), \
                 patch.object(setup, 'install_packages') as npm:
                with self.assertRaisesRegex(ValueError, 'bad hash'):
                    setup.ensure_runtime(install)
            npm.assert_not_called()
            self.assertEqual(old.read_text(), 'old')
            self.assertEqual(saved.read_text(), 'history')
            self.assertFalse((install / 'deskpet-runtime-ready.json').exists())
            self.assertFalse((root / 'runtime.installing').exists())

    def test_cancelled_install_is_not_published_and_retry_works(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); install = root / 'runtime'; cancel = threading.Event()
            def stop(stage, *_):
                fixture(stage); cancel.set()
            with patch.object(setup, 'download_node'), patch.object(setup, 'extract_node'), \
                 patch.object(setup, 'install_packages', side_effect=stop):
                with self.assertRaises(setup.SetupCancelled):
                    setup.ensure_runtime(install, cancelled=cancel)
            self.assertFalse(install.exists())
            self.assertFalse((root / 'runtime.installing').exists())
            with patch.object(setup, 'download_node'), patch.object(setup, 'extract_node'), \
                 patch.object(setup, 'install_packages', side_effect=lambda stage, *_: fixture(stage)):
                setup.ensure_runtime(install)
            self.assertTrue((install / 'deskpet-runtime-ready.json').exists())

    def test_node_checksum_failure_does_not_replace_good_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / setup.NODE_ARCHIVE
            archive.write_bytes(b'old data')
            response = io.BytesIO(b'corrupted'); response.headers = {'Content-Length': '9'}
            with patch.object(setup.urllib.request, 'urlopen', return_value=response):
                with self.assertRaisesRegex(ValueError, '校验失败'):
                    setup.download_node(root, lambda _: None, threading.Event())
            self.assertEqual(archive.read_bytes(), b'old data')
            self.assertFalse(archive.with_suffix('.zip.partial').exists())

    def test_archive_cannot_escape_private_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); archive = root / 'node.zip'
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr(f'node-v{setup.NODE_VERSION}-win-x64/../../outside.txt', 'bad')
            with self.assertRaises(ValueError):
                setup.extract_node(archive, root / 'node', threading.Event())
            self.assertFalse((root / 'outside.txt').exists())

    def test_runtime_location_survives_program_reinstallation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with patch('sys.frozen', True, create=True):
                expected = runtime_directory(data)
                self.assertTrue(expected.is_relative_to(data / 'work-runtime'))
                with patch('sys.executable', 'E:/reinstalled/TianyiPet.exe'):
                    self.assertEqual(runtime_directory(data), expected)


if __name__ == '__main__':
    unittest.main()
