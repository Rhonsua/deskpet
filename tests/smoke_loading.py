"""Real first-play responsiveness and immediate titles in both music surfaces."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import imageio_ffmpeg
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from main import Pet


class NoStartup:
    supported = False
    def enabled(self): return False


app = QApplication([])
with tempfile.TemporaryDirectory(prefix='tianyi-loading-') as scratch:
    root = Path(scratch)
    first, second = root / 'first.mp3', root / 'second.mp3'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'anullsrc=r=44100:cl=mono', '-t', '6', '-codec:a', 'libmp3lame', str(first)],
                   check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    shutil.copyfile(first, second)
    pet = Pet(data_dir=root / 'data', startup=NoStartup(),
              settings=QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
    panel = pet.panel
    try:
        panel.volume.setValue(0)
        panel.import_paths([str(first), str(second)])
        pet.toolbar.page('music')
        pet.toolbar.show()
        ticks = []
        pulse = QTimer()
        pulse.timeout.connect(lambda: ticks.append(time.monotonic()))
        pulse.start(20)
        before = time.monotonic()
        panel.play_row(0)
        assert time.monotonic()-before < .5, 'first play must return without native discovery'
        assert panel.loading.isVisible()
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            app.processEvents()
            if panel.player.position() > 100: break
            time.sleep(.005)
        assert panel.player.position() > 100, panel.status.text()
        pulse.stop()
        assert not panel.loading.isVisible()
        assert len(ticks) > 20
        gap = max(b-a for a, b in zip(ticks, ticks[1:]))
        assert gap < .4, ('GUI heartbeat blocked', gap)
        panel.step(1)
        assert panel.song_title.text() == 'second' and pet.toolbar.music_title.text() == 'second'
        panel.step(-1)
        assert panel.song_title.text() == 'first' and pet.toolbar.music_title.text() == 'first'
        panel.activate_web()
        web = panel.bilibili
        web.current_url = 'https://www.bilibili.com/video/BV1xx411c7mu/'
        web.active = True
        web.latch.reset('test')
        web.handle_event({'type': 'state', 'token': 'test', 'title': '新 B站歌名', 'playing': False})
        assert panel.song_title.text() == '新 B站歌名' and pet.toolbar.music_title.text() == '新 B站歌名'
        print(f'PASS: first play nonblocking, animated loading and heartbeat gap {gap:.3f}s; immediate MP3/Bilibili/menu titles')
    finally:
        panel.bilibili.shutdown()
        panel.shutdown_audio()
        pet.timer.stop()
        pet.fold_timer.stop()
        panel.progress_timer.stop()
        panel.store.close()
        pet.tray.hide()
        pet.toolbar.hide()
        pet.hide()
