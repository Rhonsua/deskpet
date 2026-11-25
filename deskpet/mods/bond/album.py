"""An offline, paginated keepsake book. Refreshes preserve the reader's place."""
from dataclasses import dataclass
from datetime import date
from collections import OrderedDict

from PySide6.QtCore import Qt, QRectF, QPoint, QPointF, QUrl, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                          QPen, QImage, QPixmap, QRegion, QLinearGradient, QTextLayout, QTextOption, QDesktopServices)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QToolTip
from .scrapbook import (ART_FOLIO, PaperLink, ScrapbookArt, activity_images,
                        draw_page_sticker, keepsake, page_sticker, record_body)
from .store import SCROLL_PIECES, STAGES


CHAPTERS = (('cover', '封面'), ('growth', '成长足迹'), ('actions', '互动图鉴'),
            ('music', '听歌纪念'), ('days', '日常留笺'), ('art', '画作夹'), ('scroll', '上河图'), ('week', '本周回忆'))
CHAPTER_KEYS = tuple(key for key, _ in CHAPTERS)
INK = '#344c58'
MUTED = '#596e70'
ACCENT = '#357b91'


def font(size, bold=False, serif=False):
    value = QFont('SimSun' if serif else 'Microsoft YaHei UI')
    value.setPixelSize(size)
    value.setBold(bold)
    return value


def text_pages(text, width=310, lines_per_page=11, *, typeface=None):
    """Wrap plain text with Qt's Unicode layout; no truncation or HTML parsing."""
    lines = []
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    typeface = typeface or font(16)
    for paragraph in str(text).split('\n'):
        if not paragraph:
            lines.append('')
            continue
        layout = QTextLayout(paragraph, typeface)
        layout.setTextOption(option)
        # Qt indexes UTF-16 code units, not Python Unicode code points.
        encoded = paragraph.encode('utf-16-le')
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start, length = line.textStart(), line.textLength()
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
    def __init__(self, store, parent=None, *, defer=False, art=None):
        super().__init__(parent)
        self.store = store
        self.section = 'cover'
        self.index = 0
        self.pages = {}
        self.recent = ()
        self.cover_links = ()
        self.pinned = ''
        self.record_keys = frozenset()
        self._fingerprint = None
        self._weekly_stamp = None
        self._weekly_pages = None
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
            QPushButton[paperLink="true"] {background:transparent;border:1px solid transparent;border-radius:4px;padding:0;}
            QPushButton[paperLink="true"]:hover {background:rgba(64,130,143,20);border-color:#9bbdb8;}
            QPushButton[paperLink="true"]:focus {border:2px solid #357b91;}
            QPushButton[ribbon="true"] {background:#f8f4e7;border:1px solid #c6c8b5;border-radius:4px;
                padding:1px 3px;font-size:11px;color:#476366;}
            QPushButton[ribbon="true"]:checked {background:#f1ddaa;border-color:#b2945d;color:#654e23;}
            QPushButton[ribbon="true"]:hover, QPushButton[ribbon="true"]:focus {border:1px solid #478395;}
        ''')
        layout = QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.canvas = BookCanvas(self, art);layout.addWidget(self.canvas,1)
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
        fingerprint = (self.store.revision('collection','state','preferences','daily'),
                       state['affinity'],state['nickname'],state['created'],date.today())
        if fingerprint == self._fingerprint:
            if self.section == 'week' and self._refresh_week():
                self.update_controls()
            return
        records = self.store.memories()
        anchor = None
        if self.pages:
            page = self.current_pages[self.index]
            anchor = (page.key, page.part)
        self._fingerprint = fingerprint
        self.pages = {key: [] for key, _ in CHAPTERS}
        self.pages['cover'] = [Page('portrait', '洛天依', kind='portrait'),
                               Page('title', '和你，一点一滴', kind='title')]
        self.pages['art'] = [Page('official', '官方画作', kind='folio'),
                             Page('fan', '同人画作', kind='folio')]
        self.pages['scroll'] = [Page('river', '洛天依上河图', lines=('2012—2026 · 画片随每日互动解锁',), kind='river')]
        if self.canvas.river is not None:
            self.canvas.river.refresh_progress()
        recorded = {r['id']: r for r in records}
        self.record_keys = frozenset(recorded)
        self.record_counts = dict.fromkeys(self.pages, 0)
        self.latest = dict.fromkeys(self.pages)
        chapter_titles = dict(CHAPTERS)
        def link(record):
            key = record['id']
            detail = chapter_titles[chapter_for(key)]
            if key.startswith('diary:') and record['detail']:
                detail += ' · ' + ' '.join(record['detail'].split())
            return PaperLink(record['title'], detail, key, record['at'][:10])

        self.recent = tuple(link(record) for record in records[:3])
        pin = self.store.preference('book_pin','')
        self.pinned = pin if isinstance(pin,str) and pin in recorded else ''
        if self.pinned:
            others = [entry for entry in self.recent if entry.target != self.pinned]
            self.cover_links = (link(recorded[self.pinned]), *others[:2])
        else:
            self.cover_links = self.recent
        for record in records:
            key = chapter_for(record['id'])
            self.record_counts[key] += 1
            if self.latest[key] is None:
                self.latest[key] = record
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
                cached=make_pages(record['id'], record['title'], record_body(record['id'], record['detail']),
                                  record['at'][:10], kind)
                self._record_page_cache[cache_key]=cached
            self._record_page_cache.move_to_end(cache_key)
            if len(self._record_page_cache)>512:self._record_page_cache.popitem(last=False)
            self.pages[chapter] += cached
        if self.store.stage >= 2:
            self.pages['week'] = self._weekly_pages or [Page('week', '这一周，和你', kind='week')]
            if self.section == 'week':
                self._refresh_week()
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

    def _refresh_week(self):
        if self.store.stage < 2:
            return False
        stamp = (date.today(), self.store.revision('daily','listening','collection','shows'))
        if stamp == self._weekly_stamp:
            return False
        self._weekly_pages = make_pages('week', '这一周，和你', self.store.weekly(),
                                        '只收录本地真实记录', 'week')
        self._weekly_stamp = stamp
        self.pages['week'] = self._weekly_pages
        self.index = min(self.index, len(self._weekly_pages)-1)
        return True

    def _show_page(self, section, index):
        origin = (CHAPTER_KEYS.index(self.section), self.index)
        destination = (CHAPTER_KEYS.index(section), index)
        if destination != origin:
            self.canvas.begin_turn(origin, destination)
            self.section, self.index = section, index
        if section == 'week':
            self._refresh_week()
        self.update_controls()

    def set_section(self, section):
        if self._fingerprint is None:self.reload()
        if section not in self.pages:
            return
        self._show_page(section, self.index if section == self.section else 0)
        self.canvas.setFocus(Qt.OtherFocusReason)

    def open_record(self, key):
        section = chapter_for(key)
        index = next((i for i, page in enumerate(self.pages[section]) if page.key == key), None)
        if index is None:
            return
        self._show_page(section, index - index % self.step)
        self.canvas.setFocus(Qt.OtherFocusReason)

    def links_for(self, page):
        if page.kind == 'title':
            return self.cover_links
        if page.kind == 'folio':
            return ART_FOLIO[page.key]
        return ()

    def toggle_pin(self, key):
        if key in self.record_keys:
            self.store.configure('book_pin', '' if key == self.pinned else key)
            self.reload()

    def turn(self, direction):
        step = self.step
        section = self.section
        chapter = CHAPTER_KEYS.index(section)
        target = self.index + direction*step
        if direction < 0 and self.index == 0:
            if chapter == 0:
                return
            section = CHAPTER_KEYS[chapter-1]
            last = len(self.pages[section])-1
            target = last - last % step
        elif target >= len(self.current_pages):
            if chapter == len(CHAPTER_KEYS)-1:
                return
            section, target = CHAPTER_KEYS[chapter+1], 0
        else:
            target = max(0, target)
        self._show_page(section, target)

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
            button.setToolTip('洛天依上河图 · 每日互动收集画片，可赏画或拼图' if key == 'scroll' else
                              '官方画作与同人插画、曲绘的原始发布页' if key == 'art' else
                              f'{dict(CHAPTERS)[key]} · 已收录 {count} 则' if key not in ('cover','week')
                              else ('本周回忆 · 信赖阶段开启' if key == 'week' else '封面与扉页'))
        if self.section == 'cover':
            summary = f'珍藏 {sum(self.record_counts.values())} 则回忆   /   {self.book_stage_count()} 个阶段已抵达'
        elif self.section == 'week':
            summary = '本周回忆 · 只整理真实留下的本地记录' if self.store.stage >= 2 else '本周回忆 · 信赖阶段开启'
        elif self.section == 'art':
            summary = '画作夹 · 选择作品可查看原始发布页'
        elif self.section == 'scroll':
            summary = f'洛天依上河图 · 已收集 {self.store.scroll_unlocked()}/{SCROLL_PIECES} 幅 · 2012—2026'
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
    TURN_MS = 220

    def __init__(self, book, art=None):
        super().__init__(book)
        self.book = book
        self.setMinimumHeight(330)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('天依成长纪念册；左右方向键翻页')
        self.setToolTip('点击页角，或按 ← / → 翻页；上方书签可直达章节')
        self.art = art if art is not None else ScrapbookArt()
        activity_images().ready.connect(self.update)
        self.link_buttons = []
        self.pin_buttons = []
        self.river = None
        self.old = None
        self.turn_origin = None
        self.progress = 1.
        self.direction = 1
        self.animation = QVariantAnimation(self)
        self.animation.setEndValue(1.)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._animate)
        self.animation.finished.connect(self._finish)
        self._book_rect = QRectF();self._drag_origin=None;self._dragged=False

    def begin_turn(self, origin, destination):
        # A reversal swaps the two sheets. Their shared edge stays at the same screen coordinate.
        start = 1. - self.progress if self.turn_origin == destination else 0.
        self.animation.stop()
        self._finish()
        self.direction = 1 if destination > origin else -1
        if not self.isVisible() or start >= 1.:
            return
        # Navigation buttons and the page number are live child widgets. Capture only the paper.
        ratio = self.devicePixelRatioF()
        paper = QPixmap(self.size()*ratio)
        paper.setDevicePixelRatio(ratio)
        paper.fill(Qt.transparent)
        self.render(paper, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
        if self.river is not None and self.river.isVisible():
            self.river.render(paper, self.river.pos())
        self.old = paper
        self.turn_origin = origin
        self.animation.setDuration(max(1, round(self.TURN_MS * (1. - start))))
        self.animation.setStartValue(start)
        self.progress = start
        self.animation.start()

    def _animate(self, value):
        self.progress = float(value)
        self.update()

    def _finish(self):
        self.old = None
        self.turn_origin = None
        self.progress = 1.
        if self.book.pages:
            self._place_river()
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
            self.book._show_page(self.book.section, 0)
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
            columns=(len(buttons)+1)//2
            for i,button in enumerate(buttons):
                row,col=divmod(i,columns)
                count=min(columns,len(buttons)-row*columns)
                tab_w=(w-(count-1)*gap)/count
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
        controls=(self.book.previous,self.book.position,self.book.next,self.book.export_button)
        if self.book.step == 2 and w >= 600:
            nav_w, status_w, next_w = 84, 126, 117
            x = left + (w-nav_w-status_w-next_w)/2
            for control, cw in zip(controls, (nav_w,status_w,next_w)):
                control.setGeometry(round(x),footer_y,cw,footer_h)
                x += cw
            self.book.export_button.setGeometry(round(left+w-121),footer_y,105,footer_h)
        else:
            x=left
            for control,fraction in zip(controls,sizes):
                cw=w*fraction;control.setGeometry(round(x),footer_y,max(1,round(cw)-2),footer_h);x+=cw
        self._place_links(scale,left,top)
        self._place_river()

    def _place_river(self):
        show = (self.book.section == 'scroll' and self.book.current_pages[0].kind == 'river'
                and self.old is None and self.isVisible())
        if not show:
            if self.river is not None:
                self.river.hide()
            return
        if self.river is None:
            from .river_scroll import RiverFolio
            self.river = RiverFolio(self.book.store, self)
            self.river.completed.connect(self.book.reload)
        width, scale, left, top = self._geometry()
        self.river.setGeometry(round(left + 15 * scale), round(top + 12 * scale),
                               round((width - 30) * scale), round(462 * scale))
        self.river.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self.book.pages:
            self._place_river()

    @staticmethod
    def _link_rect(page, row):
        return QRectF(38, (231 if page.kind == 'title' else 209) + row * 66, 326, 59)

    def _place_links(self, scale, left, top):
        used = 0
        pins = 0
        pages = self.book.current_pages[self.book.index:self.book.index + self.book.step]
        for side, page in enumerate(pages):
            if not page.part and not page.locked and page.kind in ('stage','record','memory','sticker') and page.key in self.book.record_keys:
                if pins == len(self.pin_buttons):
                    pin = QPushButton(self)
                    pin.setProperty('ribbon', True)
                    pin.setCheckable(True)
                    pin.setCursor(Qt.PointingHandCursor)
                    pin.clicked.connect(lambda checked=False, b=pin: self.book.toggle_pin(b.key))
                    self.pin_buttons.append(pin)
                pin = self.pin_buttons[pins]
                pins += 1
                pin.key = page.key
                selected = page.key == self.book.pinned
                pin.setChecked(selected)
                pin.setText('取下书签' if selected else '夹到扉页')
                pin.setAccessibleName(pin.text() + ' · ' + page.title)
                pin.setToolTip('取下这枚书签' if selected else '把扉页的书签夹在这一则回忆')
                pin.setGeometry(round(left+(side*self.PAGE_W+286)*scale),round(top+27*scale),
                                round(78*scale),max(19,round(24*scale)))
                pin.show()
            for row, entry in enumerate(self.book.links_for(page)):
                if used == len(self.link_buttons):
                    button = QPushButton(self)
                    button.setProperty('paperLink', True)
                    button.setCursor(Qt.PointingHandCursor)
                    button.clicked.connect(lambda checked=False, b=button: self._follow_link(b))
                    self.link_buttons.append(button)
                button = self.link_buttons[used]
                used += 1
                button.entry = entry
                button.external = page.kind == 'folio'
                hint = ('打开原作网页' if button.external else '翻到这则回忆') + ' · ' + entry.title
                button.setAccessibleName(hint)
                button.setToolTip(hint + '\n' + entry.detail + ('  ' + entry.stamp if entry.stamp else ''))
                rect = self._link_rect(page, row)
                button.setGeometry(round(left + (side * self.PAGE_W + rect.x()) * scale),
                                   round(top + rect.y() * scale), round(rect.width() * scale),
                                   round(rect.height() * scale))
                button.show()
        for button in self.link_buttons[used:]:
            button.hide()
        for pin in self.pin_buttons[pins:]:
            pin.hide()

    def _follow_link(self, button):
        if button.external:
            if not QDesktopServices.openUrl(QUrl(button.entry.target)):
                QToolTip.showText(button.mapToGlobal(button.rect().center()), '无法打开默认浏览器', button)
        else:
            self.book.open_record(button.entry.target)

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
            self._title(p, page)
        elif page.kind == 'folio':
            self._folio(p, page)
        elif page.kind == 'river':
            self._text(p,(38,64,326,68),page.title,22,INK,True,True)
        else:
            chapter = dict(CHAPTERS)[self.book.section]
            self._text(p,(38,27,300,25),chapter,13,ACCENT)
            if page.kind in ('sticker', 'record'):
                p.fillRect(QRectF(38,56,34,3),QColor('#c9ae77' if page.kind=='sticker' else '#80abad'))
                if page.part or len(page.lines) > 4:
                    self._emblem(p, page, 326, 98)
            elif page.kind == 'stage':
                self._text(p,(293,65,65,58),f'{int(page.key.split(":")[-1])+1:02d}' if page.key.startswith('stage:') else '01',
                           38,'#d5d9c8',True,True,Qt.AlignCenter)
            title_width = 321 if page.kind in ('sticker','record') and not page.part and len(page.lines)<=4 else 242
            self._text(p,(38,64,title_width,68),page.title+(' · 续' if page.part else ''),22,
                       MUTED if page.locked else INK,True,True)
            p.setPen(QPen(QColor('#acbfba'),1));p.drawLine(QPointF(38,147),QPointF(364,147))
            stamp = ('首次收录  /  ' if page.kind in ('sticker','record') else '') + page.date
            self._text(p,(38,153,326,25),stamp,12,ACCENT if not page.locked else MUTED)
            for i, line in enumerate(page.lines):
                self._text(p,(44,192+i*23,316,23),line,16,MUTED if page.locked else INK)
            if page.kind in ('sticker','record','memory') and not page.part and len(page.lines) <= 4:
                self._keepsake(p, page)
            if page.kind == 'stage':
                self._stage_path(p, page)
            elif page.kind == 'empty':
                self._flower(p,201,427,1.1)
        sticker = self._margin_sticker(page)
        if sticker is not None:
            draw_page_sticker(p, *sticker)
        self._text(p,(30,486,340,21),f'—  {number:02d}  —',11,MUTED,align=Qt.AlignCenter)

    def _margin_sticker(self, page):
        if page.kind in ('portrait', 'river') or page.key.startswith('pending:'):
            return None
        choice = page_sticker(self.book.store.value['created'], page.key, page.part)
        if choice is None:
            return None
        pose, on_right = choice
        bottom = 447 if page.kind == 'stage' else 477
        clear_from = 192 + 23 * len(page.lines) + 6
        size = 78
        if page.kind in ('title', 'folio'):
            links = self.book.links_for(page)
            if links:
                clear_from = self._link_rect(page, len(links)-1).bottom() + 6
            if page.kind == 'title' and len(self.book.recent) == 1:
                clear_from = max(clear_from, 358)
        elif page.kind in ('sticker', 'record', 'memory') and not page.part and len(page.lines) <= 4:
            # The pasted keepsake occupies the middle of short entries.
            size = 56
        size = min(size, bottom - clear_from)
        if size < 46:
            return None
        x = self.PAGE_W - 22 - size if on_right else 22
        return pose, QRectF(x, bottom-size, size, size)

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
        p.save()
        p.translate(199, 357)
        p.rotate(2 if page.kind == 'record' else -3)
        paper = {'record': '#e4eeeb', 'sticker': '#f5eddb', 'memory': '#f1e8df'}[page.kind]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(85, 76, 53, 27))
        p.drawRoundedRect(QRectF(-110,-66,223,148),3,3)
        p.setBrush(QColor(paper))
        p.setPen(QPen(QColor('#d4cbb7'), .8))
        p.drawRoundedRect(QRectF(-113,-70,223,148),3,3)
        if page.kind == 'record':
            p.setPen(QPen(QColor('#a7c2bd'), 1, Qt.DashLine))
            p.drawLine(QPointF(77,-64), QPointF(77,72))
            p.save();p.translate(93,3);p.rotate(-90)
            self._text(p,(-60,-8,120,16),page.date.replace('-','.'),10,MUTED,align=Qt.AlignCenter)
            p.restore()
        else:
            self._tape(p, -113, -68, -17)
            self._tape(p, 61, 60, -19)
        art_rect = QRectF(-91 if page.kind == 'record' else -77,-65,143,135)
        if not self.art.draw(p, keepsake(page.key), art_rect):
            self._emblem(p,page,art_rect.center().x(),art_rect.center().y())
        p.restore()

    @staticmethod
    def _tape(p, x, y, angle):
        p.save();p.translate(x,y);p.rotate(angle)
        p.fillRect(QRectF(0,0,55,13),QColor(196, 172, 113, 108))
        p.setPen(QPen(QColor(255, 247, 220, 160), 1.4))
        for i in range(4, 51, 7):
            p.drawLine(QPointF(i, 11), QPointF(i+6, 2))
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
        wash.setColorAt(0,QColor('#e5f1e7'));wash.setColorAt(.55,QColor('#c2e3e3'));wash.setColorAt(1,QColor('#a2cbd1'))
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
        for radius in (123,135,146):p.drawEllipse(QPointF(213,251),radius,radius)
        self._text(p,(48,34,295,19),'洛天依',13,'#3c676a')
        self._text(p,(47,58,300,44),'成长纪念集',31,'#214e59',True,True)
        if not self.art.draw(p, 'jasmine', QRectF(57,106,304,337)):
            self._flower(p,201,262,3)

    def _title(self, p, page):
        state = self.book.store.value
        self.art.draw(p, 'letter', QRectF(273,23,94,95))
        owner = state['nickname'] or '你和天依'
        owner = QFontMetricsF(font(13)).elidedText(owner+' 的珍藏',Qt.ElideRight,235)
        self._text(p,(39,31,238,24),owner,13,ACCENT)
        self._text(p,(38,62,242,48),page.title,28,INK,True,True)
        started = state['created'][:10].replace('-', '.')
        self._text(p,(40,146,326,25),f'始于 {started}     ·     {STAGES[self.book.store.stage][0]}  /  亲密度 {state["affinity"]}',12,MUTED)
        p.setPen(QPen(QColor('#b9c9bd'),1));p.drawLine(QPointF(39,187),QPointF(364,187))
        self._text(p,(38,195,215,29),'书签与最近收录' if self.book.pinned else '最近收录',19,INK,True,True)
        self._text(p,(242,198,120,23),f'共 {sum(self.book.record_counts.values())} 则',12,MUTED,align=Qt.AlignRight)
        self._draw_links(p, page)
        if len(self.book.recent) == 1:
            self._text(p,(40,312,310,40),'摸摸头，或写一则新的留笺。',14,MUTED)

    def _folio(self, p, page):
        official = page.key == 'official'
        self.art.draw(p, 'wings' if official else 'jasmine', QRectF(214,23,153,173))
        self._text(p,(39,55,165,23),'画作夹',13,ACCENT)
        self._text(p,(37,81,180,48),page.title,29,INK,True,True)
        self._text(p,(39,145,177,23),'蓝羽 · 桌宠新绘' if official else '茉莉 · 桌宠新绘',12,MUTED)
        self._draw_links(p, page)

    def _draw_links(self, p, page):
        for row, entry in enumerate(self.book.links_for(page)):
            r = self._link_rect(page, row)
            x,y,w,h = r.x(),r.y(),r.width(),r.height()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#f1f2e9' if page.kind == 'title' else '#f0eee2'))
            p.drawRoundedRect(r,4,4)
            if entry.stamp:
                self._text(p,(x+5,y+3,44,20),entry.stamp[5:7]+' 月',10,MUTED,align=Qt.AlignCenter)
                self._text(p,(x+5,y+20,44,31),entry.stamp[8:10],22,ACCENT,True,True,Qt.AlignCenter)
                p.setPen(QPen(QColor('#c6d2c7'),1));p.drawLine(QPointF(x+54,y+11),QPointF(x+54,y+h-11))
                offset=65
            else:
                p.fillRect(QRectF(x+7,y+9,3,h-18),QColor('#89afb2' if page.key=='official' else '#c7a17e'))
                offset=21
            room=w-offset-24
            title=QFontMetricsF(font(16,True)).elidedText(entry.title,Qt.ElideRight,room)
            pinned = bool(entry.stamp and entry.target == self.book.pinned)
            subtitle = ('扉页书签 · ' if pinned else '') + entry.detail
            detail=QFontMetricsF(font(12)).elidedText(subtitle,Qt.ElideRight,room)
            self._text(p,(x+offset,y+5,room+1,25),title,16,INK,True)
            self._text(p,(x+offset,y+30,room+1,23),detail,12,MUTED)
            p.setBrush(Qt.NoBrush);p.setPen(QPen(QColor(ACCENT),1.5,Qt.SolidLine,Qt.RoundCap))
            end=QPointF(r.right()-11,r.center().y())
            p.drawLine(QPointF(end.x()-5,end.y()-5),end)
            p.drawLine(end,QPointF(end.x()-5,end.y()+5))
            if pinned:
                ribbon = QPainterPath()
                ribbon.moveTo(r.right()-29, y)
                ribbon.lineTo(r.right()-16, y)
                ribbon.lineTo(r.right()-16, y+15)
                ribbon.lineTo(r.right()-22.5, y+11)
                ribbon.lineTo(r.right()-29, y+15)
                ribbon.closeSubpath()
                p.fillPath(ribbon,QColor('#c6a15c'))

    def _blank(self,p):
        self.art.draw(p,'letter',QRectF(153,229,96,97))


def render_memory_card(title, body, stamp, art, illustration):
    """Lay out the complete original text, including lines beyond the open spread."""
    heading = font(32, True, True)
    writing = font(22)
    titles = [line for part in text_pages(title, 568, typeface=heading) for line in part]
    lines = [line for part in text_pages(body, 723, typeface=writing) for line in part]
    rule_y = max(185, 95 + 42 * len(titles))
    body_y = rule_y + 56
    height = max(465, body_y + 34 * len(lines) + 64)
    image = QImage(864, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#407685'))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.fillRect(QRectF(14,14,836,height-28), QColor('#fffaf0'))
        painter.setPen(QPen(QColor('#cbb98c'),1))
        painter.drawRect(QRectF(24,24,816,height-48))
        painter.setFont(font(17));painter.setPen(QColor(ACCENT))
        painter.drawText(QPointF(65,65), '洛天依  /  成长纪念集')
        art.draw(painter, illustration, QRectF(656,32,139,140))
        painter.setFont(heading);painter.setPen(QColor(INK))
        for index, line in enumerate(titles):
            painter.drawText(QPointF(64,119+index*42), line)
        painter.setPen(QPen(QColor('#b8c8bb'),1))
        painter.drawLine(QPointF(65,rule_y),QPointF(799,rule_y))
        painter.setFont(font(16));painter.setPen(QColor(MUTED))
        painter.drawText(QPointF(65,rule_y+28), stamp)
        painter.setFont(writing);painter.setPen(QColor(INK))
        for index, line in enumerate(lines):
            painter.drawText(QPointF(65,body_y+22+index*34), line)
    finally:
        painter.end()
    return image
