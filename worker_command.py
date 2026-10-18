"""Source and frozen builds use the same isolated helper protocols."""
from pathlib import Path
import sys


def worker_command(kind):
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).with_name('TianyiWorker.exe')), ['--' + kind + '-worker']
    executable = Path(sys.executable)
    if executable.name.lower() == 'pythonw.exe':
        executable = executable.with_name('python.exe')
    return str(executable), [str(Path(__file__).with_name(kind + '_player_worker.py'))]
