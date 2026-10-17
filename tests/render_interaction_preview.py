"""Render the actual Qt animation states and toolbar into a small demonstration GIF."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import imageio_ffmpeg
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from main import Pet


class PreviewStartup:
    supported = True
    def enabled(self):
        return False
    def set_enabled(self, value):
        pass


with tempfile.TemporaryDirectory() as scratch:
    app = QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
    pet = Pet(data_dir=Path(scratch) / 'data', startup=PreviewStartup(),
              settings=QSettings(str(Path(scratch) / 'settings.ini'), QSettings.Format.IniFormat))
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.toolbar.page('home')
    pet.toolbar.show()
    app.processEvents()
    stage = QWidget()
    stage.resize(720, 470)
    stage.setStyleSheet('QWidget { background: #EDF2F5; color: #415B6B; font-family: "Microsoft YaHei UI"; } QLabel { background: transparent; }')
    title = QLabel('洛天依 · 桌面互动预览', stage)
    title.setStyleSheet('font-size: 20px; font-weight: 600;')
    title.setGeometry(24, 20, 600, 32)
    action_name = QLabel(stage)
    action_name.setStyleSheet('font-size: 13px; color: #7395A6;')
    action_name.setGeometry(24, 60, 500, 25)
    toolbar = QLabel(stage)
    toolbar.setGeometry(24, 110, 336, 260)
    toolbar.setPixmap(pet.toolbar.grab())
    figure = QLabel(stage)
    figure.setGeometry(420, 130, 260, 310)
    speech = QLabel(stage)
    speech.setGeometry(390, 76, 290, 60)
    footer = QLabel('右键菜单  /  点头摸摸  /  按住拖动  /  投喂互动', stage)
    footer.setStyleSheet('color: #8AA0AC; font-size: 11px;')
    footer.setGeometry(24, 422, 385, 24)
    stage.show()
    output = Path(__file__).resolve().parents[1] / 'preview'
    output.mkdir(exist_ok=True)
    frames = Path(scratch) / 'frames'
    frames.mkdir()
    scenarios = [('idle', '待机：呼吸与眨眼', 18, '我在这里陪你。'),
                 ('happy', '摸头：闭眼挥手与爱心回应', 18, '嘿嘿，头发要被摸乱啦。'),
                 ('lift', '提起：惊讶表情与轻轻摇摆', 18, '欸——要去哪里呀？'),
                 ('land', '放下：落地回弹', 8, '站稳啦！'),
                 ('eat', '投喂：抱着包子吃一口', 24, '啊呜……好吃！'),
                 ('sleep', '休息：背身盖被子，轻轻呼吸', 24, '被子盖好啦……晚安。'),
                 ('phone', '熬夜：被窝玩手机，点击收起', 24, '再看一小会儿……就一小会儿。'),
                 ('music', '听歌：摇摆与音符', 18, '一起听喜欢的歌吧。')]
    index = 0
    for action, caption, count, words in scenarios:
        pet.dragging = action == 'lift'
        pet.sleeping = action == 'sleep'
        pet.using_phone = action == 'phone'
        pet.playing = action == 'music'
        pet.action = action if action not in ('sleep', 'phone', 'music') else 'idle'
        start = time.monotonic()
        pet.action_start = start
        pet.bubble.say(words, 30000)
        app.processEvents()
        speech.setPixmap(pet.bubble.grab())
        action_name.setText(caption)
        for frame in range(count):
            pet.phase = start + frame / 12
            pet.update()
            app.processEvents()
            figure.setPixmap(pet.grab())
            app.processEvents()
            shot = stage.grab()
            shot.save(str(frames / f'{index:04d}.png'))
            if action == 'happy' and frame == 7:
                shot.save(str(output / 'interactive-preview.png'))
            index += 1
    pet.tray.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    pet.hide()
    pet.panel.store.close()
    stage.hide()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-framerate', '12',
                    '-i', str(frames / '%04d.png'), '-vf',
                    'split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer',
                    '-loop', '0', str(output / 'interactive-preview.gif')], check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print('Rendered interaction preview:', output / 'interactive-preview.gif')
