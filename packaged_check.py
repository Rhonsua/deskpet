"""Isolated installed-build smoke test, with no changes to actual user settings."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave


def run():
    native = '--native-live2d' in sys.argv
    if not native:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QSettings, QUrl
    from PySide6.QtWidgets import QApplication
    from main import Pet
    report = Path(sys.argv[sys.argv.index('--report') + 1]).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    result = {'ok': False}
    app = QApplication([])
    class NoStartup:
        supported = False
        def enabled(self): return False
    with tempfile.TemporaryDirectory(prefix='tianyi-packaged-', dir=report.parent, ignore_cleanup_errors=True) as scratch:
        os.environ['LOCALAPPDATA'] = scratch
        pet = None
        try:
            pet = Pet(data_dir=Path(scratch) / 'data', startup=NoStartup(),
                      settings=QSettings(str(Path(scratch) / 'test.ini'), QSettings.Format.IniFormat))
            assert len(pet.frames) == 10
            pet.grab()
            if native:
                assert pet.variant == 'live2d' and pet.live2d_renderer is not None, pet.panel.character_note.text()
                for activity in ('idle', 'sing', 'sleep', 'phone', 'mouse_wave'):
                    frame = pet.live2d_renderer.frame(activity, 1.0)
                    assert not frame.isNull() and frame.hasAlphaChannel(), activity
                    assert any(frame.pixelColor(x, y).alpha() > 100
                               for x in range(0, frame.width(), 8)
                               for y in range(0, frame.height(), 8)), activity
                assert pet.set_variant('refined') and pet.live2d_renderer is None
                assert pet.set_variant('live2d') and pet.live2d_renderer is not None
                result['live2d'] = True
            # Exercise the installed chat package and resources without any API.
            pet.open_chat()
            chat = pet.chat_window
            assert chat.personality.id == 'luotianyi' and not chat.personality_warning
            assert chat.client is None
            pet.set_mode('sleep')
            chat.input.setPlainText(r'\int_0^5x exp(x^2)dx等于多少')
            chat.send_message()
            history = chat.store.history(chat.character)
            assert len(history) == 2 and '不太会解' in history[-1]['content']
            assert chat.client is None and pet.behavior.mode == 'sleep'
            chat.close()
            from app_icon import application_icon
            icon = application_icon()
            assert len(icon.availableSizes()) == 9
            assert pet.tray.icon().pixmap(32).toImage() == icon.pixmap(32).toImage()
            result.update(chat=True, local_scope=True, avatar_icon=True)
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
                if getattr(pet, 'chat_window', None):
                    pet.chat_window.shutdown()
                pet.panel.bilibili.shutdown()
                pet.panel.shutdown_audio()
                pet.timer.stop()
                pet.panel.progress_timer.stop()
                pet.panel.store.close()
                pet.tray.hide()
                pet.hide()
                pet.close_live2d()
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
