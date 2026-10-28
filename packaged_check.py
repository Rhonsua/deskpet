"""Isolated installed-build smoke test, with no changes to actual user settings."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave


def check_music_features(pet, app, scratch, result):
    """Exercise newly frozen dependencies and workers with synthetic data only."""
    from netease_music.direct import prepare_request
    from netease_music.account_probe import AccountProbe
    from netease_music.browser_login import BrowserLogin
    import numpy as np
    music = pet.music_companion
    assert music is not None, pet.music_startup_error
    music.open(0)
    assert music.window is not None and music.tabs.count() == 3
    music.timer.stop()
    address, payload, header = prepare_request('https://music.163.com/api/w/nuser/account/get', {}, '')
    assert address.endswith('/weapi/w/nuser/account/get') and len(payload['encSecKey']) == 256 and not header
    probe = AccountProbe(lambda cookie: (dict(userId='77'), 'verified'))
    probe.poll('MUSIC_U=synthetic-only')
    probe.results.get(timeout=3)
    music.lyrics.update('netease:77', 1000, True)
    music.lyrics.import_online('77', '打包检查', '[00:01]这是清晰的测试歌词', 'netease:77')
    music.lyrics.configure(color='#ffd666', left_passthrough=True)
    overlay = music.lyrics.overlay
    assert overlay.isVisible() and overlay.text_color == '#ffd666'
    if '--native-live2d' in sys.argv:
        assert overlay.right_click.hook
    menu = overlay.make_menu()
    assert menu.colors.actions()[0].text() == '白色'
    menu.deleteLater()
    music.lyrics.configure(enabled=False)
    assert not overlay.isVisible() and not overlay.right_click.hook
    music.window.hide()
    login = BrowserLogin()
    sessions, errors = [], []
    login.completed.connect(sessions.append)
    login.failed.connect(errors.append)
    login.worker_args = ['--self-test', '--fixture-fetch']
    try:
        login.start()
        deadline = time.monotonic() + 40
        while not sessions and not errors and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert sessions and sessions[0]['uid'] == '77' and not errors, errors
    finally:
        login.cancel()
    audio = Path(scratch) / 'beat-check.wav'
    rate = 48000
    samples = np.zeros(rate * 8, dtype=np.float32)
    pulse = np.sin(2 * np.pi * 440 * np.arange(1600) / rate) * np.exp(-np.arange(1600) / 240)
    for index in range(0, len(samples) - len(pulse), rate // 2):
        samples[index:index + len(pulse)] = pulse
    stereo = np.column_stack((samples, -samples))
    with wave.open(str(audio), 'wb') as output:
        output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        output.writeframes((stereo * 24000).astype('<i2').tobytes())
    music.beats.set_source('local:' + str(audio))
    music.beats.analyze()
    deadline = time.monotonic() + 40
    while music.beats.analyzing and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert music.beats.analysis and abs(music.beats.analysis['bpm'] - 120) < 3, music.beats.status
    result.update(music_tools=True, netease_crypto=True, netease_browser=True,
                  lyrics_menu=True, beat_worker=True)


def check_mod_package(pet, app, archive_path, result):
    """Check an empty host first, then install only inside the disposable data root."""
    from datetime import datetime, timedelta
    import importlib.util
    import zipfile
    from PySide6.QtCore import QDateTime
    from pet_mods.host import ModHost

    host = pet.mod_host
    assert host is not None and host.manager.manifests() == []
    assert list(host.packages_dir.iterdir()) == []
    assert not (pet.panel.data_dir / 'mods' / 'goals').exists()
    if getattr(sys, 'frozen', False):
        assert importlib.util.find_spec('pet_mods.goals') is None, 'goal code was bundled in main application'
        result['goal_code_excluded'] = True
    result['mods_empty_by_default'] = True
    if archive_path is None:
        return
    with zipfile.ZipFile(archive_path) as archive:
        expected = {'goals/' + name for name in ('mod.json', 'entry.py', '__init__.py', 'mod.py',
                    'store.py', 'widget.py', 'README.txt', 'LICENSE')}
        assert set(archive.namelist()) == expected, archive.namelist()
        assert archive.testzip() is None
        assert sum(item.file_size for item in archive.infolist()) < 16 * 1024 * 1024
        # Explicit whitelist above makes archive traversal impossible.
        archive.extractall(host.packages_dir)
    host.shutdown()
    host.deleteLater()
    pet.mod_host = host = ModHost(pet)
    manifests = host.manager.manifests()
    assert len(manifests) == 1 and manifests[0].id == 'goals', host.discovery_warning
    assert not host.manager.is_enabled('goals')
    assert not (pet.panel.data_dir / 'mods' / 'goals').exists(), 'discovery executed goal package'
    assert host.manager.set_enabled('goals', True), host.manager.error('goals')
    editor = host.manager.create_widget('goals')
    assert editor is not None, host.manager.error('goals')
    try:
        now = datetime.now()
        editor.title_input.setText('冻结版外置目标测试')
        editor.deadline_input.setDateTime(QDateTime(now + timedelta(hours=1)))
        editor.steps_input.setPlainText('检查加载\n保存目标')
        editor.save_button.click()
        goal_id = editor.current_id
        assert goal_id is not None and editor.mod.store.get(goal_id)['title'] == '冻结版外置目标测试'
        delivered = []
        host.manager._deliver = lambda text: delivered.append(text) or True
        assert host.manager.set_policy(quiet_enabled=False, sound_enabled=False)
        host.tick()
        assert len(delivered) == 1 and '冻结版外置目标测试' in delivered[0]
        assert editor.mod.store.get(goal_id)['last_reminded'] is not None
        host.tick()
        assert len(delivered) == 1
    finally:
        editor.close()
        editor.deleteLater()
    assert host.manager.set_enabled('goals', False)
    assert host.manager.set_enabled('goals', True), host.manager.error('goals')
    restored = host.manager.create_widget('goals')
    assert restored is not None and restored.mod.store.get(goal_id)['title'] == '冻结版外置目标测试'
    restored.close()
    restored.deleteLater()
    assert host.manager.set_enabled('goals', False)
    result['external_goal_package'] = True


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
    mod_archive = Path(sys.argv[sys.argv.index('--mod-pack') + 1]).resolve() if '--mod-pack' in sys.argv else None
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
                assert pet.live2d_renderer.motions.walk_spec is not None
                for activity in ('idle', 'sing', 'sleep', 'phone', 'mouse_wave', 'lift',
                                 'walk-left', 'walk-right'):
                    frame = pet.live2d_renderer.frame(activity, 1.0)
                    assert not frame.isNull() and frame.hasAlphaChannel(), activity
                    assert any(frame.pixelColor(x, y).alpha() > 100
                               for x in range(0, frame.width(), 8)
                               for y in range(0, frame.height(), 8)), activity
                assert pet.set_variant('refined') and pet.live2d_renderer is None
                assert pet.walk_spec is not None and pet.walk_frames
                assert pet.set_variant('live2d') and pet.live2d_renderer is not None
                result.update(live2d=True, live2d_walk=True, static_walk=True)
            # Check the frozen chat helper can initialize its network runtime.
            # EOF terminates it without contacting a model or reading user data.
            import subprocess
            from worker_command import worker_command
            program, arguments = worker_command('chat')
            helper = subprocess.run([program, *arguments], input=b'', capture_output=True,
                                    timeout=30, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert b'"type": "ready"' in helper.stdout, 'Chat helper did not become ready'
            result['chat_worker'] = True
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
            check_mod_package(pet, app, mod_archive, result)
            check_music_features(pet, app, scratch, result)
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
                if getattr(pet, 'music_companion', None):
                    pet.music_companion.shutdown()
                if getattr(pet, 'mod_host', None):
                    pet.mod_host.shutdown()
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
