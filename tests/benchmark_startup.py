"""Measure imports, construction and first frame with disposable user data.

Run in a fresh Python process for each sample. No timing assertion: machines vary.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
started = time.perf_counter()
from main import Pet
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
imported = time.perf_counter()
app = QApplication([])


class NoStartup:
    supported = False
    def enabled(self):
        return False


with tempfile.TemporaryDirectory(prefix='tianyi-startup-') as scratch:
    os.environ['LOCALAPPDATA'] = scratch
    pet = Pet(data_dir=Path(scratch) / 'data', startup=NoStartup(),
              settings=QSettings(str(Path(scratch) / 'settings.ini'), QSettings.Format.IniFormat))
    constructed = time.perf_counter()
    app.processEvents()
    assert not pet.grab().isNull()
    painted = time.perf_counter()
    assert pet.panel._player is None and pet.panel._audio is None
    print(f'import={imported-started:.3f}s construct={constructed-imported:.3f}s '
          f'first_frame={painted-started:.3f}s', flush=True)
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.bilibili.watchdog.stop()
    if pet.panel._audio_router is not None:
        pet.panel._audio_router.poll.stop()
    if pet.panel._player is not None:
        pet.panel._player.stop()
    pet.tray.hide()
    pet.panel.shutdown_audio()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()
