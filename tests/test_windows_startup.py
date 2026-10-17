import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from windows_startup import WindowsStartup, launch_command, winreg


@unittest.skipUnless(os.name == 'nt', 'Windows-specific launch and registry tests')
class StartupTests(unittest.TestCase):
    def setUp(self):
        self.key_path = r'Software\TianyiPet\StartupTests' + '\\' + uuid.uuid4().hex
        self.manager = WindowsStartup(key_path=self.key_path, command='"test app.exe" --autostart')

    def tearDown(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key_path)
        except FileNotFoundError:
            pass

    def test_enable_disable_preserves_other_values(self):
        self.assertFalse(self.manager.enabled())
        self.manager.set_enabled(True)
        self.assertTrue(self.manager.enabled())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'OtherApp', 0, winreg.REG_SZ, 'keep')
        self.manager.set_enabled(False)
        self.assertFalse(self.manager.enabled())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
            self.assertEqual(winreg.QueryValueEx(key, 'OtherApp')[0], 'keep')

    def test_existing_command_for_old_location_is_not_reported_enabled(self):
        self.manager.set_enabled(True)
        moved = WindowsStartup(key_path=self.key_path, command='"new location.exe" --autostart')
        self.assertFalse(moved.enabled())
        moved.set_enabled(True)
        self.assertTrue(moved.enabled())

    def test_windowless_command_handles_unicode_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix='天依 自启 ') as scratch:
            script = Path(scratch) / '启动 测试.py'
            marker = Path(scratch) / 'result.json'
            script.write_text("import sys, json\nfrom pathlib import Path\n"
                              "Path(__file__).with_name('result.json').write_text(json.dumps(sys.argv[1:]))\n",
                              encoding='utf-8')
            command = launch_command(sys.executable, script, frozen=False)
            result = subprocess.run(command, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(marker.read_text()), ['--autostart'])
            if Path(sys.executable).with_name('pythonw.exe').is_file():
                self.assertIn('pythonw.exe', command)

    def test_packaged_app_does_not_need_python_script(self):
        command = launch_command(r'C:\天依 桌宠\deskpet.exe', frozen=True)
        self.assertTrue(command.endswith(' --autostart'))
        self.assertNotIn('main.py', command)


if __name__ == '__main__':
    unittest.main()
