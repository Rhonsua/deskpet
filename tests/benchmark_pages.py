"""Repeatable page/open/stream timings with isolated settings, no model requests."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from main import Pet
from visual_style import APPEARANCE_REVISION


class Startup:
    supported = False
    def enabled(self):
        return False


app = QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 9))


def measure(name, action):
    start = time.perf_counter()
    action()
    app.processEvents()
    print(f'{name}: {(time.perf_counter() - start) * 1000:.1f} ms', flush=True)


with tempfile.TemporaryDirectory(prefix='pet-pages-') as directory:
    settings = QSettings(str(Path(directory) / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'refined')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=Path(directory), settings=settings, startup=Startup())
    app.processEvents()
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    try:
        measure('music_open', lambda: pet.open_tools(0))
        measure('settings_open', lambda: pet.open_tools(2))
        measure('growth_tab', lambda: pet.panel.tabs.setCurrentIndex(1))
        measure('settings_again', lambda: pet.panel.tabs.setCurrentIndex(2))
        pet.panel.hide()
        measure('chat_first_open', pet.open_chat)
        chat = pet.chat_window
        measure('persona_tab', lambda: chat.tabs.setCurrentIndex(2))
        measure('api_tab', lambda: chat.tabs.setCurrentIndex(1))
        measure('chat_tab', lambda: chat.tabs.setCurrentIndex(0))
        for i in range(30):
            chat.store.add_turn(chat.character, f'{i}：' + '今天想聊聊音乐。' * 100,
                                '一起听喜欢的歌吧。' * 100)
        measure('history_60_messages', chat.render_history)
        chat.pending = (chat.character, '今天有什么好玩的事？')
        chat.render_history(chat.pending[1], '')
        def stream():
            for i in range(30):
                chat.partial_text = '[开心]' + '今天也一起加油！' * (i + 1)
                chat.flush_partial()
                app.processEvents()
        measure('stream_30_updates_with_history', stream)
        chat.pending = None
        chat.close()
        measure('chat_reopen', pet.open_chat)
    finally:
        if getattr(pet, 'chat_window', None):
            pet.chat_window.shutdown()
            pet.chat_window.hide()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.close_live2d()
        pet.tray.hide()
        pet.panel.store.close()
        pet.panel.hide()
        pet.hide()
