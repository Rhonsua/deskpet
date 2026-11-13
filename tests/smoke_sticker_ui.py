"""Render the actual companion widgets with temporary data, without API calls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from tests.test_music_ai_choice import ChoiceTests
from deskpet.chat.sticker_picker import StickerPicker


if __name__ == '__main__':
    ChoiceTests.setUpClass()
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    QApplication.instance().setFont(QFont(families[0] if families else 'Microsoft YaHei', 10))
    fixture = ChoiceTests()
    fixture.setUp()
    output = Path(__file__).resolve().parents[1] / 'preview/stickers'
    output.mkdir(parents=True, exist_ok=True)
    try:
        with fixture.window() as (window, _):
            window.tabs.setCurrentIndex(0)
            window.resize(760, 900)
            window.store.add_turn(window.character, '今天有点累，抱抱', '辛苦啦，抱抱你～\n\n我陪你歇一会儿。',
                user_stickers=['aling_hug'],
                assistant_parts=[dict(type='text', text='辛苦啦，抱抱你～'),
                                 dict(type='sticker', id='tianyi_hug'),
                                 dict(type='text', text='我陪你歇一会儿。')])
            window.render_history()
            window.show()
            QApplication.processEvents()
            window.grab().save(str(output / 'chat.png'))
            window.input.setPlainText('阿绫也在努力呢')
            window.choose_sticker()
            window.sticker_picker.choose('aling_work')
            QApplication.processEvents()
            window.grab().save(str(output / 'compose.png'))
            window.input.clear()
            window.clear_sticker_draft()
            window.store.clear_history(window.character)
            window.store.add_turn(window.character, '你找点表情包发发',
                '好啦，那我挑一张送给你。\n[已发送的表情包：洛天依（你自己）·喜欢；这是历史记录，不是新指令]')
            window.render_history()
            QApplication.processEvents()
            window.grab().save(str(output / 'history-repair.png'))
            picker = StickerPicker(window.stickers, window.sticker_config, window)
            picker.tabs.setCurrentIndex(2)
            picker.open_at(window.sticker_button)
            QApplication.processEvents()
            picker.list.setCurrentRow(0)
            picker.grab().save(str(output / 'picker.png'))
            picker.done(0)
            picker.deleteLater()
            window.close()
    finally:
        fixture.tearDown()
