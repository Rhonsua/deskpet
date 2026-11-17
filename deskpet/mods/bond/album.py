"""An offline, paginated keepsake book. Refreshes preserve the reader's place."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from collections import OrderedDict

from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                          QPen, QPixmap, QLinearGradient, QTextLayout, QTextOption)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from .store import STAGES


CHAPTERS = (('cover', '封面'), ('growth', '成长足迹'), ('actions', '互动图鉴'),
            ('music', '听歌纪念'), ('days', '日常留笺'), ('week', '本周回忆'))
INK = '#344c58'
MUTED = '#7c8989'
ACCENT = '#357b91'


def font(size, bold=False, serif=False):
    value = QFont('SimSun' if serif else 'Microsoft YaHei UI')
    value.setPixelSize(size)
    value.setBold(bold)
    return value


def text_pages(text, width=310, lines_per_page=11):
    """Wrap plain text with Qt's Unicode layout; no truncation or HTML parsing."""
    lines = []
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    for paragraph in str(text).split('\n'):
        if not paragraph:
            lines.append('')
            continue
        layout = QTextLayout(paragraph, font(16))
        layout.setTextOption(option)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start, length = line.textStart(), line.textLength()
            # Qt indexes UTF-16 code units, not Python Unicode code points.
            encoded = paragraph.encode('utf-16-le')
            lines.append(encoded[start*2:(start+length)*2].decode('utf-16-le'))
        layout.endLayout()
    return [tuple(lines[i:i+lines_per_page]) for i in range(0, len(lines), lines_per_page)] or [()]


@dataclass(frozen=True)
class Page:
    key: str
    title: str
    date: str = ''
    lines: tuple = ()
    kind: str = 'memory'
    part: int = 0
    locked: bool = False


def chapter_for(key):
    if key == 'first-meeting' or key.startswith('stage:'):
        return 'growth'
    if key.startswith(('action:', 'combo:', 'need:')):
        return 'actions'
    if key.startswith(('song:', 'show:', 'quiz:')) or key in ('first-rhythm', 'first-quiz', 'first-performance'):
        return 'music'
    return 'days'


def make_pages(key, title, body, stamp='', kind='memory', locked=False):
    if len(title) > 18:
        body = title+'\n\n'+body
        title = title[:16]+'…'
    return [Page(key, title, stamp, lines, kind, i, locked)
            for i, lines in enumerate(text_pages(body))]


class MemoryBook(QWidget):
    back_requested = Signal()
    close_requested = Signal()
    export_requested = Signal()
    def __init__(self, store, parent=None, *, defer=False):
        super().__init__(parent)
        self.store = store
        self.section = 'cover'
        self.index = 0
        self.pages = {}
        self._fingerprint = None
        self._record_page_cache=OrderedDict()
        self.setObjectName('memoryBook')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet('''
            QWidget#memoryBook {background:transparent;}
            QPushButton[bookmark="true"] {background:#e2e9e7;border:0;border-bottom:3px solid #c6d8d5;
                border-radius:3px;padding:3px 2px;color:#5c757c;font-size:12px;}
            QPushButton[bookmark="true"]:checked {background:#4b8293;color:#fff;border-bottom:3px solid #dbbc76;}
            QPushButton[bookmark="true"]:hover {background:#93bac7;color:#fff;}
            QPushButton[pageTurn="true"] {background:#fffaf0;border:1px solid #cfcdbe;
                padding:3px 3px;border-radius:12px;font-size:13px;color:#476772;}
            QPushButton[pageTurn="true"]:disabled {color:#b4b8b2;border-color:#e3e3d9;}
        ''')
        layout = QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.canvas = BookCanvas(self);layout.addWidget(self.canvas,1)
        self.bookmarks = {}
        for key, title in CHAPTERS:
            button = QPushButton(title,self.canvas);button.setProperty('bookmark',True);button.setCheckable(True)
            button.setAccessibleName(title+'书签');button.clicked.connect(lambda _=False,k=key:self.set_section(k))
            self.bookmarks[key] = button
        self.back = QPushButton('返回',self.canvas);self.back.setProperty('bookmark',True);self.back.setAccessibleName('返回陪伴首页');self.back.clicked.connect(self.back_requested.emit)
        self.close_book = QPushButton('关闭',self.canvas);self.close_book.setProperty('bookmark',True);self.close_book.setAccessibleName('关闭纪念册');self.close_book.clicked.connect(self.close_requested.emit)
        self.catalogue = QLabel(self.canvas);self.catalogue.hide()
        self.previous = QPushButton('‹ 上一页',self.canvas);self.next = QPushButton('下一页 ›',self.canvas)
        self.export_button = QPushButton('导出纪念卡',self.canvas);self.export_button.setAccessibleName('导出纪念卡');self.export_button.clicked.connect(self.export_requested.emit)
        for button in (self.previous,self.next,self.export_button):button.setProperty('pageTurn',True)
        self.previous.clicked.connect(lambda:self.turn(-1));self.next.clicked.connect(lambda:self.turn(1))
        self.position = QLabel(self.canvas);self.position.setAlignment(Qt.AlignCenter)
        self.position.setStyleSheet('color:#536d72;font-size:12px;background:transparent;')
        if defer:
            self.pages={key:[Page('pending:'+key,'翻开后查看',kind='empty')] for key,_ in CHAPTERS}
            self.pages['cover']=[Page('portrait','洛天依',kind='portrait'),Page('title','和你，一点一滴',kind='title')]
            self.record_counts={key:0 for key,_ in CHAPTERS}
            self.latest={key:None for key,_ in CHAPTERS}
            self.update_controls()
        else:self.reload()

    @property
    def step(self):
        return 2 if self.canvas.width() >= 680 else 1

    @property
    def current_pages(self):
        return self.pages[self.section]

    def reload(self):
        state = self.store.value
        fingerprint = (self.store.revision('collection','state','daily','listening','shows'),
                       state['affinity'],state['nickname'],state['created'],date.today())
        if fingerprint == self._fingerprint:
            return
        records = self.store.memories()
        weekly = self.store.weekly() if self.store.stage >= 2 else ''
        anchor = None
        if self.pages:
            page = self.current_pages[self.index]
            anchor = (page.key, page.part)
        self._fingerprint = fingerprint
        self.pages = {key: [] for key, _ in CHAPTERS}
        self.pages['cover'] = [Page('portrait', '洛天依', kind='portrait'),
                               Page('title', '和你，一点一滴', kind='title')]
        recorded = {r['id']: r for r in records}
        self.record_counts = {key: sum(chapter_for(r['id']) == key for r in records)
                              for key, _ in CHAPTERS}
        self.latest = {key: next((r for r in records if chapter_for(r['id']) == key), None)
                       for key, _ in CHAPTERS}
        for i, (title, goal, unlock) in enumerate(STAGES):
            key = 'stage:'+str(i) if i else 'first-meeting'
            entry = recorded.get(key)
            reached = self.store.stage >= i
            stamp = entry['at'][:10] if entry else ('尚未抵达' if not reached else '已抵达 · 日期未记录')
            body = ('这一页，已经有了我们的足迹。' if reached else '未来的这一页，留给慢慢相伴的日子。')
            body += f'\n\n亲密度 {goal}\n\n阶段开放\n{unlock}'
            self.pages['growth'] += make_pages(key, title, body, stamp, 'stage', not reached)
        for record in records:
            chapter = chapter_for(record['id'])
            if chapter == 'growth':
                continue
            kind = 'sticker' if chapter == 'actions' else ('record' if chapter == 'music' else 'memory')
            cache_key=(record['id'],record['title'],record['detail'],record['at'][:10],kind)
            cached=self._record_page_cache.get(cache_key)
            if cached is None:
                cached=make_pages(record['id'], record['title'], record['detail'], record['at'][:10], kind)
                self._record_page_cache[cache_key]=cached
            self._record_page_cache.move_to_end(cache_key)
            if len(self._record_page_cache)>512:self._record_page_cache.popitem(last=False)
            self.pages[chapter] += cached
        if self.store.stage >= 2:
            self.pages['week'] = make_pages('week', '这一周，和你', weekly, '只收录本地真实记录', 'week')
        else:
            self.pages['week'] = make_pages('week-locked', '留给未来的一封信',
                '到达「信赖」后，这里会整理本周留下的互动、听歌与日常。\n\n不必赶路，慢慢来就好。', '信赖阶段开启', 'week', True)
        for key, title in CHAPTERS:
            if not self.pages[key]:
                self.pages[key] = make_pages('empty:'+key, '下一段回忆，等我们写下',
                    {'actions':'亲自触发过的小动作，会连同第一次发生的日期，收进这本册子。',
                     'music':'一起完整听完的歌、猜歌挑战和小演出，会在这里留下纪念。',
                     'days':'今天想说的话、生日与相遇纪念，都有属于它们的一页。'}.get(key, ''),
                    '还没有收录', 'empty')
        if anchor:
            self.index = next((i for i, p in enumerate(self.current_pages) if (p.key,p.part) == anchor),
                              min(self.index, len(self.current_pages)-1))
        self.update_controls()

    def set_section(self, section):
        if self._fingerprint is None:self.reload()
        if section not in self.pages:
            return
        if section != self.section:
            self.canvas.begin_turn(1)
            self.section, self.index = section, 0
        self.update_controls()
        self.canvas.setFocus(Qt.OtherFocusReason)

    def turn(self, direction):
        target = self.index + direction*self.step
        chapters = [key for key,_ in CHAPTERS]
        chapter = chapters.index(self.section)
        if direction < 0 and self.index == 0 and chapter > 0:
            self.set_section(chapters[chapter-1])
            self.index = ((len(self.current_pages)-1)//self.step)*self.step
            self.update_controls()
            return
        if direction > 0 and target >= len(self.current_pages) and chapter < len(chapters)-1:
            self.set_section(chapters[chapter+1])
            return
        if direction < 0:
            target = max(0, target)
        if not 0 <= target < len(self.current_pages) or target == self.index:
            return
        self.canvas.begin_turn(direction)
        self.index = target
        self.update_controls()

    def update_controls(self):
        self.previous.setEnabled(self.index > 0 or self.section != 'cover')
        self.next.setEnabled(self.index+self.step < len(self.current_pages) or self.section != 'week')
        self.next.setText('翻开纪念集  ›' if self.section=='cover' and self.index+self.step>=2 else '下一页  ›')
        end = min(self.index+self.step, len(self.current_pages))
        numbers = f'{self.index+1}—{end}' if end > self.index+1 else str(end)
        self.position.setText(f'{dict(CHAPTERS)[self.section]}  ·  {numbers} / {len(self.current_pages)}')
        for key, button in self.bookmarks.items():
            button.setChecked(key == self.section)
            count = self.record_counts.get(key, 0)
            button.setToolTip(f'{dict(CHAPTERS)[key]} · 已收录 {count} 则' if key not in ('cover','week')
                              else ('本周回忆 · 信赖阶段开启' if key == 'week' else '封面与扉页'))
        if self.section == 'cover':
            summary = f'珍藏 {sum(self.record_counts.values())} 则回忆   /   {self.book_stage_count()} 个阶段已抵达'
        elif self.section == 'week':
            summary = '本周回忆 · 只整理真实留下的本地记录' if self.store.stage >= 2 else '本周回忆 · 信赖阶段开启'
        else:
            count = self.record_counts[self.section]
            latest = self.latest[self.section]
            summary = f'已收录 {count} 则'
            if self.section == 'growth':
                summary = f'已抵达 {self.book_stage_count()} / {len(STAGES)} 个阶段'
            if latest:
                summary += f'   /   最近收录 {latest["at"][:10]} · {latest["title"]}'
        self.catalogue.setText(QFontMetricsF(self.catalogue.font()).elidedText(summary, Qt.ElideRight, max(120, self.width()-30)))
        self.catalogue.setToolTip(summary)
        self.canvas.setAccessibleDescription('\n'.join(p.title+'\n'+'\n'.join(p.lines)
            for p in self.current_pages[self.index:self.index+self.step]))
        self.canvas._place_controls()
        self.canvas.update()

    def book_stage_count(self):
        return self.store.stage + 1


class BookCanvas(QWidget):
    PAGE_W, PAGE_H = 402, 568

    def __init__(self, book):
        super().__init__(book)
        self.book = book
        self.setMinimumHeight(330)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('天依成长纪念册；左右方向键翻页')
        self.setToolTip('点击页角，或按 ← / → 翻页；上方书签可直达章节')
        self.portrait = QPixmap(str(Path(__file__).with_name('assets')/'tianyi-cover.webp'))
        self.old = None
        self.progress = 1.
        self.direction = 1
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(220)
        self.animation.setStartValue(0.)
        self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._animate)
        self.animation.finished.connect(self._finish)
        self._book_rect = QRectF();self._drag_origin=None;self._dragged=False

    def begin_turn(self, direction):
        self.animation.stop()
        self.old = None
        self.progress = 1.
        if not self.isVisible():
            return
        self.old = self.grab()
        self.direction = direction
        self.progress = 0.
        self.animation.start()

    def _animate(self, value):
        self.progress = float(value)
        self.update()

    def _finish(self):
        self.old = None
        self.progress = 1.
        self.update()

    def resizeEvent(self, event):
        self.animation.stop()
        self._finish()
        if self.book.pages:
            self.book.update_controls()
        super().resizeEvent(event)
        self._place_controls()

    def hideEvent(self, event):
        self.animation.stop()
        self._finish()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.book.turn(-1)
        elif event.key() in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space):
            self.book.turn(1)
        elif event.key() == Qt.Key_Home:
            self.book.index = 0
            self.book.update_controls()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self._book_rect.contains(event.position()):
            self._drag_origin=event.globalPosition().toPoint();self._window_origin=self.window().pos();self._dragged=False
            event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton and self.window().isWindow():
            delta=event.globalPosition().toPoint()-self._drag_origin
            if delta.manhattanLength() >= 5:self._dragged=True
            if self._dragged:self.window().move(self._window_origin+delta)
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._dragged and event.button() == Qt.LeftButton and self._book_rect.contains(event.position()):
            rect = self._book_rect
            if event.position().y() > rect.bottom()-rect.height()*.22:
                if event.position().x() < rect.left()+rect.width()*.22:
                    self.book.turn(-1)
                elif event.position().x() > rect.right()-rect.width()*.22:
                    self.book.turn(1)
        self._drag_origin=None
        super().mouseReleaseEvent(event)

    def _geometry(self):
        width=self.PAGE_W*(2 if self.book.step==2 else 1)
        scale=min((self.width()-38)/(width+24),(self.height()-90)/(self.PAGE_H+28))
        scale=max(.1,scale)
        return width,scale,(self.width()-width*scale)/2,(self.height()-self.PAGE_H*scale)/2+18

    def _place_controls(self):
        if not hasattr(self.book,'back'):return
        width,scale,left,top=self._geometry();w=width*scale
        buttons=[self.book.back]+list(self.book.bookmarks.values())+[self.book.close_book]
        gap=2;tab_h=26
        if self.book.step==1:
            for i,button in enumerate(buttons):
                row=i//4;col=i%4;tab_w=(w-3*gap)/4
                button.setGeometry(round(left+col*(tab_w+gap)),round(top-(2-row)*tab_h+4),max(1,round(tab_w)),tab_h)
            self.book.previous.setText('‹ 上页');self.book.next.setText('下页 ›');self.book.export_button.setText('导出')
            sizes=[.21,.29,.22,.28]
        else:
            tab_w=(w-gap*(len(buttons)-1))/len(buttons)
            for i,button in enumerate(buttons):
                button.setGeometry(round(left+i*(tab_w+gap)),round(top-tab_h+4),max(1,round(tab_w)),tab_h)
            self.book.previous.setText('‹ 上一页')
            self.book.next.setText('翻开纪念集  ›' if self.book.section=='cover' and self.book.index+self.book.step>=2 else '下一页  ›')
            self.book.export_button.setText('导出纪念卡')
            sizes=[.19,.21,.34,.26]
        footer_y=round(top+525*scale);footer_h=max(24,min(34,round(32*scale)))
        x=left
        for control,fraction in zip((self.book.previous,self.book.position,self.book.next,self.book.export_button),sizes):
            cw=w*fraction;control.setGeometry(round(x),footer_y,max(1,round(cw)-2),footer_h);x+=cw

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        spread = self.book.step == 2
        width,scale,left,top = self._geometry()
        self._book_rect = QRectF(left, top, width*scale, self.PAGE_H*scale)
        painter.save()
        painter.translate(left, top)
        painter.scale(scale, scale)
        for inset, alpha in ((12,10),(8,15),(4,22)):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(41,61,62,alpha))
            painter.drawRoundedRect(QRectF(-inset,5-inset,width+inset*2,self.PAGE_H+inset*2),12,12)
        painter.setBrush(QColor('#477c8b'))
        painter.drawRoundedRect(QRectF(-10,-9,width+20,self.PAGE_H+23),8,8)
        painter.setPen(QPen(QColor('#c4c595'),.8))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(-5,-4,width+10,self.PAGE_H+13),5,5)
        for dy in (10,7,4):
            painter.setBrush(QColor('#dcd8c9'))
            painter.setPen(QPen(QColor('#babfb5'),.6))
            painter.drawRoundedRect(QRectF(-1,dy,width+2,self.PAGE_H),3,3)
        for side in range(2 if spread else 1):
            painter.save()
            painter.translate(side*self.PAGE_W,0)
            index = self.book.index+side
            self._paper(painter, side == 0, spread)
            if index < len(self.book.current_pages):
                self._page(painter, self.book.current_pages[index], index+1)
            else:
                self._blank(painter)
            painter.restore()
        if spread:
            shade = QLinearGradient(self.PAGE_W-19,0,self.PAGE_W+22,0)
            shade.setColorAt(0,QColor(90,77,53,0))
            shade.setColorAt(.45,QColor(90,77,53,40))
            shade.setColorAt(.52,QColor(255,255,248,120))
            shade.setColorAt(1,QColor(90,77,53,0))
            painter.fillRect(QRectF(self.PAGE_W-19,0,41,self.PAGE_H),shade)
        painter.restore()
        if self.old is not None and self.progress < 1:
            # A clipped page wipe leaves the stationary page in place; no giant 3D warping.
            area = self._book_rect
            edge = area.right()-area.width()*self.progress if self.direction > 0 else area.left()+area.width()*self.progress
            painter.save()
            clip = QRectF(area.left()-18,area.top()-16,edge-area.left()+18,area.height()+36) if self.direction > 0 else QRectF(edge,area.top()-16,area.right()-edge+18,area.height()+36)
            painter.setClipRect(clip)
            painter.drawPixmap(0,0,self.old)
            painter.restore()
            shadow = QLinearGradient(edge-12,0,edge+12,0)
            shadow.setColorAt(0,QColor(60,65,60,0));shadow.setColorAt(.5,QColor(60,65,60,35));shadow.setColorAt(1,QColor(60,65,60,0))
            painter.fillRect(QRectF(edge-12,area.top(),24,area.height()),shadow)
        painter.end()

    def _paper(self, p, left, spread):
        gradient = QLinearGradient(0,0,self.PAGE_W,0)
        gradient.setColorAt(0,QColor('#f8f4e9' if left else '#efeadd'))
        gradient.setColorAt(.12,QColor('#fffdf5'))
        gradient.setColorAt(.87,QColor('#fffdf5'))
        gradient.setColorAt(1,QColor('#eee8da' if left and spread else '#f6f2e6'))
        p.fillRect(QRectF(0,0,self.PAGE_W,self.PAGE_H),gradient)
        p.setPen(QPen(QColor(134,143,117,12),.6))
        for y in range(4,self.PAGE_H,7):
            p.drawLine(QPointF(8,y),QPointF(self.PAGE_W-8,y))
        p.setPen(QPen(QColor('#d9d4be'),1))
        p.drawLine(QPointF(28,481),QPointF(374,481))

    def _text(self, p, rect, value, size=16, color=INK, bold=False, serif=False, align=Qt.AlignLeft):
        p.setFont(font(size,bold,serif));p.setPen(QColor(color))
        p.drawText(QRectF(*rect),int(align|Qt.AlignVCenter|Qt.TextWordWrap),str(value))

    def _flower(self, p, x, y, size=1):
        p.save();p.translate(x,y);p.scale(size,size)
        p.setPen(QPen(QColor('#b7d2ce'),1))
        for i in range(5):
            p.save();p.rotate(i*72)
            p.setBrush(QColor('#f4fbf7' if i%2 else '#a8ddea'))
            p.drawEllipse(QRectF(-6,-21,12,22));p.restore()
        p.setBrush(QColor('#77a97e'));p.drawEllipse(QRectF(-4,-4,8,8));p.restore()

    def _page(self, p, page, number):
        if page.kind == 'portrait':
            self._portrait(p)
        elif page.kind == 'title':
            self._title(p)
        else:
            chapter = dict(CHAPTERS)[self.book.section]
            chapter_number = [k for k,_ in CHAPTERS].index(self.book.section)
            self._text(p,(38,27,300,25),f'CHAPTER {chapter_number:02d}  /  {chapter}',11,MUTED)
            if page.kind in ('sticker', 'record'):
                p.setPen(QPen(QColor('#dfdcc8'),1))
                p.setBrush(QColor('#f1f1e3' if page.kind == 'sticker' else '#e8efeb'))
                p.drawRoundedRect(QRectF(32,61,338,78),5,5)
                if not page.part and len(page.lines) <= 4:
                    self._text(p,(293,77,65,38),'贴纸' if page.kind == 'sticker' else ('唱片' if page.key.startswith('song:') else '留票'),12,ACCENT,align=Qt.AlignCenter)
                else:
                    self._emblem(p, page, 326, 98)
            elif page.kind == 'stage':
                self._text(p,(293,65,65,58),f'{int(page.key.split(":")[-1])+1:02d}' if page.key.startswith('stage:') else '01',
                           38,'#d5d9c8',True,True,Qt.AlignCenter)
            self._text(p,(40,64,242,68),page.title+(' · 续' if page.part else ''),22,
                       MUTED if page.locked else INK,True,True)
            p.setPen(QPen(QColor('#acbfba'),1));p.drawLine(QPointF(38,147),QPointF(364,147))
            stamp = ('首次收录  /  ' if page.kind in ('sticker','record') else '') + page.date
            self._text(p,(38,153,326,25),stamp,12,ACCENT if not page.locked else MUTED)
            for i, line in enumerate(page.lines):
                self._text(p,(44,192+i*23,316,23),line,16,MUTED if page.locked else INK)
            if page.kind in ('sticker','record') and not page.part and len(page.lines) <= 4:
                self._keepsake(p, page)
            if page.kind == 'stage':
                self._stage_path(p, page)
            elif page.kind == 'empty':
                self._flower(p,201,427,1.1)
            elif not page.part:
                label = self._collection_label(page) if page.kind in ('sticker','record') else '一页小事，也值得好好珍藏。'
                self._text(p,(44,452,310,22),label,11,MUTED)
        self._text(p,(30,486,340,21),f'—  {number:02d}  —',11,MUTED,align=Qt.AlignCenter)

    @staticmethod
    def _collection_label(page):
        if page.key.startswith('song:'): return '听歌珍藏  /  一起完整听过的旋律'
        if page.key.startswith(('show:', 'first-performance')): return '演出留票  /  一起完成的小舞台'
        if page.key.startswith(('quiz:', 'first-quiz')): return '猜歌纪念  /  旋律里的小默契'
        if page.key.startswith('combo:'): return '组合互动  /  属于我们的小默契'
        if page.key.startswith('need:'): return '照料留念  /  回应过的小小需要'
        if page.kind == 'record': return '节奏纪念  /  留下真实发生的瞬间'
        return '互动贴纸  /  第一次，值得好好收藏'

    def _emblem(self, p, page, x, y):
        """Original vector keepsakes, selected by factual record type, never title guesses."""
        p.save();p.translate(x,y)
        music = page.kind == 'record'
        disc = page.key.startswith('song:')
        p.setPen(QPen(QColor('#ffffff'),5))
        p.setBrush(QColor('#e2bb79' if music else '#accbc1'))
        p.drawEllipse(QRectF(-31,-31,62,62))
        p.setPen(QPen(QColor('#426a70'),2.2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if disc:
            p.setBrush(QColor('#35555c'));p.drawEllipse(QRectF(-27,-27,54,54))
            p.setPen(QPen(QColor('#729197'),.8))
            for radius in (15,20,24):p.drawEllipse(QPointF(0,0),radius,radius)
            p.setPen(Qt.NoPen);p.setBrush(QColor('#e9d9a9'));p.drawEllipse(QRectF(-9,-9,18,18))
            p.setBrush(QColor('#fffaf0'));p.drawEllipse(QRectF(-2,-2,4,4))
        elif music:
            p.setBrush(QColor('#fff7de'));p.drawRoundedRect(QRectF(-24,-17,48,34),3,3)
            p.drawLine(QPointF(-13,-14),QPointF(-13,14))
            if page.key.startswith(('quiz:','first-quiz')):
                self._text(p,(-10,-14,32,28),'?',25,ACCENT,True,align=Qt.AlignCenter)
            else:
                p.drawLine(QPointF(7,-10),QPointF(7,7));p.drawLine(QPointF(7,-10),QPointF(16,-7))
                p.setBrush(QColor('#426a70'));p.drawEllipse(QRectF(0,4,8,6))
        elif any(token in page.key for token in ('feed','eat','snack')):
            p.setBrush(QColor('#fff4d6'));p.drawRoundedRect(QRectF(-20,-8,40,23),8,8)
            p.drawLine(QPointF(-23,-9),QPointF(23,-9))
            p.drawLine(QPointF(-5,-17),QPointF(-1,-23))
            p.drawLine(QPointF(7,-17),QPointF(11,-23))
        elif any(token in page.key for token in ('sleep','dream','quiet')):
            moon = QPainterPath();moon.moveTo(13,-21);moon.cubicTo(-24,-23,-28,20,7,23)
            moon.cubicTo(-6,10,-4,-10,13,-21)
            p.setBrush(QColor('#fff0b9'));p.drawPath(moon)
        elif any(token in page.key for token in ('sing','listen')):
            p.drawLine(QPointF(2,-19),QPointF(2,13));p.drawLine(QPointF(2,-19),QPointF(17,-15))
            p.setBrush(QColor('#fff6df'));p.drawEllipse(QRectF(-12,7,15,11))
        elif 'gaze' in page.key:
            eye=QPainterPath();eye.moveTo(-23,0);eye.quadTo(0,-27,23,0);eye.quadTo(0,27,-23,0)
            p.setBrush(QColor('#fff8e4'));p.drawPath(eye)
            p.setBrush(QColor('#426a70'));p.drawEllipse(QRectF(-7,-9,14,18))
        elif any(token in page.key for token in ('turn','mouse_wave','sway')):
            p.drawArc(QRectF(-20,-20,40,40),40*16,280*16)
            p.drawLine(QPointF(15,-17),QPointF(20,-7));p.drawLine(QPointF(20,-7),QPointF(8,-8))
        elif 'chat' in page.key:
            p.setBrush(QColor('#fff8e4'));p.drawRoundedRect(QRectF(-22,-17,44,30),8,8)
            p.drawLine(QPointF(-12,13),QPointF(-15,21))
            for xx in (-10,0,10):p.drawPoint(QPointF(xx,-2))
        else:
            heart=QPainterPath();heart.moveTo(0,18)
            heart.cubicTo(-37,-3,-14,-30,0,-12);heart.cubicTo(14,-30,37,-3,0,18)
            p.setBrush(QColor('#fff1db'));p.drawPath(heart)
            if 'headpat' in page.key:
                p.drawLine(QPointF(-18,-24),QPointF(-7,-25));p.drawLine(QPointF(8,-25),QPointF(18,-24))
        p.restore()

    def _keepsake(self, p, page):
        p.save();p.translate(201,354);p.rotate(-3 if page.kind == 'sticker' else 2)
        p.setPen(QPen(QColor('#ded9c5'),1));p.setBrush(QColor('#e2dfd0'))
        p.drawRoundedRect(QRectF(-86,-53,177,135),3,3)
        p.setBrush(QColor('#fffdf4'));p.drawRoundedRect(QRectF(-90,-57,177,135),3,3)
        p.setPen(Qt.NoPen);p.setBrush(QColor(196,210,180,160))
        p.drawRect(QRectF(-32,-65,64,17))
        p.save();p.scale(1.6,1.6);self._emblem(p,page,0,0);p.restore()
        self._text(p,(-80,52,157,20),'FIRST MEMORY  /  '+page.date.replace('-','.'),8,MUTED,align=Qt.AlignCenter)
        p.restore()

    def _stage_path(self, p, page):
        active = int(page.key.split(':')[-1]) if page.key.startswith('stage:') else 0
        # The body ends at y=445; the progress strip occupies the footer only.
        for i in range(len(STAGES)):
            x=51+i*59
            if i < len(STAGES)-1:
                p.setPen(QPen(QColor('#b8cebf' if i < self.book.store.stage else '#deded0'),2))
                p.drawLine(QPointF(x,461),QPointF(x+59,461))
            p.setPen(QPen(QColor(ACCENT if i == active else '#bac7b9'),1.5))
            p.setBrush(QColor('#76a49b' if i <= self.book.store.stage else '#fffaf0'))
            p.drawEllipse(QPointF(x,461),6 if i == active else 3.5,6 if i == active else 3.5)

    def _portrait(self, p):
        wash = QLinearGradient(0,0,402,520)
        wash.setColorAt(0,QColor('#dbf0ee'));wash.setColorAt(.55,QColor('#c3e5ef'));wash.setColorAt(1,QColor('#edf6e8'))
        p.fillRect(QRectF(14,14,374,459),wash)
        p.fillRect(QRectF(14,14,15,459),QColor('#467e8a'))
        p.setPen(QPen(QColor('#759d9e'),.6))
        for thread in range(16,29,3):p.drawLine(QPointF(thread,17),QPointF(thread,470))
        p.setPen(QPen(QColor('#b3ac77'),1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(34,19,347,448))
        # Foil corners and a cloth binding, all drawn locally without texture assets.
        for xx, yy, sx, sy in ((40,26,1,1),(375,26,-1,1),(40,460,1,-1),(375,460,-1,-1)):
            p.drawLine(QPointF(xx,yy),QPointF(xx+sx*23,yy))
            p.drawLine(QPointF(xx,yy),QPointF(xx,yy+sy*23))
        p.setPen(QPen(QColor(255,255,255,160),1))
        p.setBrush(Qt.NoBrush)
        for radius in (130,152,175):p.drawEllipse(QPointF(210,230),radius,radius)
        self._text(p,(46,29,320,25),'LUO TIANYI   /   OUR LITTLE MEMORIES',10,ACCENT)
        if not self.portrait.isNull():
            target=QRectF(90,56,222,407)
            size=self.portrait.size().scaled(int(target.width()),int(target.height()),Qt.KeepAspectRatio)
            p.drawPixmap(QRectF(target.center().x()-size.width()/2,target.top(),size.width(),size.height()),
                         self.portrait,QRectF(self.portrait.rect()))
        else:
            self._flower(p,201,215,3)
            self._text(p,(50,300,302,60),'洛 天 依',30,ACCENT,serif=True,align=Qt.AlignCenter)
        self._flower(p,55,430,.75)
        self._text(p,(264,438,106,24),'洛水天依',15,ACCENT,serif=True)
        self._text(p,(84,439,180,20),'VOL. 01 · 成长纪念集',10,ACCENT)

    def _title(self, p):
        self._flower(p,201,80,1.2)
        self._text(p,(32,116,338,23),'陪 伴 · 成 长 · 纪 念',12,ACCENT,align=Qt.AlignCenter)
        self._text(p,(30,157,342,55),'和你，一点一滴',30,INK,True,True,Qt.AlignCenter)
        self._text(p,(40,221,322,52),'把普通的日子，\n装订成闪闪发光的回忆。',16,MUTED,serif=True,align=Qt.AlignCenter)
        state=self.book.store.value
        self._text(p,(45,300,312,24),'我们的成长纪念集',13,ACCENT,align=Qt.AlignCenter)
        self._text(p,(45,331,312,25),'始于 '+state['created'][:10].replace('-',' . '),13,MUTED,align=Qt.AlignCenter)
        self._text(p,(45,365,312,26),f'{STAGES[self.book.store.stage][0]}  ·  亲密度 {state["affinity"]}',15,INK,align=Qt.AlignCenter)
        name=state['nickname'] or '你和天依'
        name=QFontMetricsF(font(13)).elidedText(name,Qt.ElideRight,280)
        self._text(p,(45,409,312,26),name+' 的珍藏',13,ACCENT,align=Qt.AlignCenter)
        self._text(p,(45,446,312,22),f'{sum(self.book.record_counts.values())} 则真实回忆  ·  {self.book.book_stage_count()} / {len(STAGES)} 个阶段',11,MUTED,align=Qt.AlignCenter)

    def _blank(self,p):
        self._flower(p,201,200,1.3)
        self._text(p,(45,254,312,70),'下一页，\n留给还没发生的美好。',18,MUTED,serif=True,align=Qt.AlignCenter)
