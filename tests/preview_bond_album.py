"""Render the real book window using an isolated, populated album."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout
from deskpet.mods.bond.album import render_memory_card
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.widget import BondWidget


def main():
    app = QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    output = ROOT / 'local-work/reports/bond-scrapbook'
    output.mkdir(parents=True, exist_ok=True)
    store = BondStore(':memory:')
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    first = (now - timedelta(days=8)).isoformat()
    diary = '今天出门忘记带伞，回来时却碰上了太阳。\n想把这点好心情也留给你。'
    with store.db:
        store.db.execute('UPDATE state SET created=?,nickname=?', (first, '小洛和我'))
        store.db.execute("UPDATE collection SET at=? WHERE id='first-meeting'", (first,))
        for days, key, title, body in (
            (0, 'diary:preview', '午后的一封留笺', diary),
            (1, 'song:preview:1', '唱片纪念 · 光与影的对白', '已共同完整听完 1 次。'),
            (2, 'action:feed', '一起吃点心', '亲自触发后收录。'),
            (3, 'action:headpat', '摸摸头', '亲自触发后收录。'),
            (4, 'show:preview', '我们的三曲小演出', '光与影的对白 · 心印 · 追光使者'),
            (5, 'diary:long', '周末的听歌手记', '一首歌听到最后，才留意到尾奏里的那几个音。'*29),
        ):
            store.card(key, title, body, now-timedelta(days=days))
    store.refresh()
    mod = SimpleNamespace(store=store, active=True, games=[], analysis_owner=None,
                          events=SimpleNamespace(summary=lambda: '', active=None),
                          services=SimpleNamespace(), guess=lambda: None, weekly_show=lambda: None)
    origin = QDialog()
    layout = QVBoxLayout(origin)
    panel = BondWidget(mod, origin)
    layout.addWidget(panel)
    origin.show()
    panel.tabs.setCurrentIndex(2)
    window, book = panel._book_window, panel.album

    def capture(section, name, width=1080, height=740, index=0):
        window.resize(width, height)
        app.processEvents()
        book.set_section(section)
        book.index = index
        book.update_controls()
        book.canvas.animation.stop()
        book.canvas._finish()
        app.processEvents()
        shot = window.grab().toImage()
        assert shot.pixelColor(0,0).alpha() == 0
        assert shot.save(str(output / (name+'.png')))

    try:
        for section in ('cover','actions','music','art','days','growth'):
            capture(section, section)
        book.toggle_pin('action:headpat')
        capture('cover','cover-with-bookmark')
        capture('cover','narrow-title',530,650,1)
        capture('art','narrow-art',530,530,1)
        capture('days','long-entry',530,650,2)
        card = render_memory_card('午后的一封留笺',diary,'收录于 '+now.date().isoformat(),
                                  book.canvas.art,'letter')
        assert card.save(str(output / 'export-card.png'))
        print('Album previews:', output)
    finally:
        window.close()
        origin.close()
        store.close()


if __name__ == '__main__':
    main()
