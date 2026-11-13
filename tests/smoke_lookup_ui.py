"""Render lookup switch and source footer using temporary data, without network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from tests.test_music_ai_choice import ChoiceTests


if __name__ == '__main__':
    ChoiceTests.setUpClass()
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    QApplication.instance().setFont(QFont(families[0] if families else 'Microsoft YaHei', 10))
    fixture = ChoiceTests()
    fixture.setUp()
    try:
        with fixture.window() as (window, _):
            window.tabs.setCurrentIndex(0)
            window.proactive_toggle.setChecked(True)
            window.proactive_interval.setValue(10)
            window.resize(760, 900)
            window.store.add_turn(window.character, '查一下《普通DISCO》，聊聊它想表达什么。',
                '查到了。我觉得它是在说，日常看起来普通，但跟着喜欢的节奏晃一晃，也能发现一点不一样的快乐。',
                sources=[dict(title='普通Disco · 洛天依、言和', url='https://www.kugou.com/song/#hash=EB805958A48D83AA5846D1FA2B8AFECB')])
            window.render_history()
            window.show()
            QApplication.processEvents()
            path = Path(__file__).resolve().parents[1] / 'preview/lookup/chat.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(path))
            window.close()
    finally:
        fixture.tearDown()
