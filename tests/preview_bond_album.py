"""Render isolated book states. Does not open the user's pet or modify its save."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from datetime import datetime, timedelta
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from deskpet.mods.bond.album import MemoryBook
from deskpet.mods.bond.store import BondStore

app=QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei UI',10))
store=BondStore(':memory:')
store.nickname('屏幕这边的你')
book=MemoryBook(store)
book.resize(1000,680)
book.show();app.processEvents()
output=ROOT/'local-work/reports/bond-refresh';output.mkdir(parents=True,exist_ok=True)
def capture(section,name):
    book.set_section(section);book.canvas.animation.stop();book.canvas._finish()
    app.processEvents();assert book.grab().save(str(output/name))
capture('cover','cover.png')
capture('growth','growth.png')
store.card('action:headpat','摸摸头','亲自触发后收录。',datetime.now())
store.card('action:sing','持麦唱歌','亲自触发后收录。',datetime.now()-timedelta(days=1))
store.card('action:feed','一起吃点心','亲自回应过的小小需要。',datetime.now()-timedelta(days=2))
store.card('action:sleep','晚安','一天结束的时候，说声晚安。',datetime.now()-timedelta(days=3))
store.card('song:preview','和你听过的第一首歌','完整听完后留下的纪念。此条仅用于隔离预览。',datetime.now())
store.card('show:preview','三曲小演出','共同完成演出后留下的纪念。',datetime.now()-timedelta(days=1))
store.card('quiz:preview','猜歌的小默契','此条是预览示例，不会写入真实存档。',datetime.now()-timedelta(days=2))
store.card('diary:test','今天想说的话','这是预览用的长段落，不会保存到桌宠。\n\n'+'把平凡的小事慢慢记下来，留在这本册子里。'*25)
book.reload();capture('actions','actions.png')
book.turn(1);book.canvas.animation.stop();book.canvas._finish();app.processEvents();book.grab().save(str(output/'actions-more.png'))
capture('music','music.png')
capture('days','long-entry.png')
book.resize(560,650);app.processEvents();capture('cover','narrow.png')
capture('music','narrow-music.png')
book.close();store.close()
print('Book previews saved:',output)
