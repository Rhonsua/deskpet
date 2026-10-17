"""Opt-in Windows sign-in launch for the current user only."""
import os
import subprocess
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def launch_command(executable=None, script=None, frozen=None):
    executable = Path(executable or sys.executable).resolve()
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if frozen:
        arguments = [str(executable), '--autostart']
    else:
        windowless = executable.with_name('pythonw.exe')
        if windowless.is_file():
            executable = windowless
        script = Path(script or Path(__file__).with_name('main.py')).resolve()
        arguments = [str(executable), str(script), '--autostart']
    return subprocess.list2cmdline(arguments)


class WindowsStartup:
    def __init__(self, key_path=RUN_KEY, value_name='TianyiDeskPet', command=None):
        self.key_path = key_path
        self.value_name = value_name
        self.command = command or launch_command()

    @property
    def supported(self):
        return os.name == 'nt' and winreg is not None

    def enabled(self):
        if not self.supported:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
                value, kind = winreg.QueryValueEx(key, self.value_name)
                return kind == winreg.REG_SZ and value == self.command
        except FileNotFoundError:
            return False

    def set_enabled(self, enabled):
        if not self.supported:
            raise OSError('开机自启仅支持 Windows')
        if enabled:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key_path,
                                    access=winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.value_name, 0, winreg.REG_SZ, self.command)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path,
                                    access=winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, self.value_name)
            except FileNotFoundError:
                pass
