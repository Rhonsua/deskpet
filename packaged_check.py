"""Isolated installed-build smoke test, with no changes to actual user settings."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave


def run():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QSettings, QUrl
    from PySide6.QtWidgets import QApplication
    from main import Pet
    report = Path(sys.argv[sys.argv.index('--report') + 1])
    result = {'ok': False}
    app = QApplication([])
    class NoStartup:
        supported = False
        def enabled(self): return False
    with tempfile.TemporaryDirectory(prefix='tianyi-packaged-', ignore_cleanup_errors=True) as scratch:
        os.environ['LOCALAPPDATA'] = scratch
        pet = None
        try:
            pet = Pet(data_dir=Path(scratch) / 'data', startup=NoStartup(),
                      settings=QSettings(str(Path(scratch) / 'test.ini'), QSettings.Format.IniFormat))
            assert len(pet.frames) == 10
            pet.grab()
            song = Path(scratch) / 'test.wav'
            with wave.open(str(song), 'wb') as file:
                file.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                file.writeframes(bytes(8000 * 2 * 4))
            panel = pet.panel
            panel.volume.setValue(0)
            panel.ensure_audio()
            panel._player.setSource(QUrl.fromLocalFile(str(song)))
            panel._player.play()
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                app.processEvents()
                if panel._player.position() > 300: break
                time.sleep(.01)
            assert panel._player.position() > 300, panel.status.text()
            panel._player.pause()
            web = panel.bilibili
            web.worker_args = ['--self-test']
            web.input.setText('https://www.bilibili.com/video/BV1xx411c7mu/')
            assert web.add_link()
            web.play_row(0)
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                app.processEvents()
                if web.playing: break
                time.sleep(.01)
            assert web.playing, web.note.text()
            result.update(ok=True, assets=len(pet.frames), audio=True, webview2=True)
        except Exception as error:
            import traceback
            result['error'] = str(error)
            result['traceback'] = traceback.format_exc()
        finally:
            if pet:
                pet.panel.bilibili.shutdown()
                pet.panel.shutdown_audio()
                pet.timer.stop()
                pet.panel.progress_timer.stop()
                pet.panel.store.close()
                pet.tray.hide()
                pet.hide()
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
