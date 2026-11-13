"""Selectable text bubbles with a locally stored, cover-cropped background."""
import html
import uuid
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, QSize, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QTextCursor, QTextTable, QTextFormat, QBrush, QMovie, QTextDocument
from PySide6.QtWidgets import QTextBrowser
from deskpet.ui.background import save_background

STICKER_DISPLAY_SIZE = 96

class ConversationView(QTextBrowser):
    def __init__(self,parent=None, *, assistant_markdown=False):
        super().__init__(parent)
        self.assistant_markdown = assistant_markdown
        self.messages=[];self.live_start=None;self.live_end=None
        self.sticker_catalog = None
        self.sticker_movies = {}
        self.sticker_frames = {}
        self._follow_latest = True
        self._scrolling_latest = False
        self.latest_scroll = QTimer(self)
        self.latest_scroll.setSingleShot(True)
        self.latest_scroll.timeout.connect(self.show_latest_message)
        self.verticalScrollBar().sliderPressed.connect(self.stop_following_latest)
        self.verticalScrollBar().actionTriggered.connect(lambda _: self.stop_following_latest())
        self.verticalScrollBar().rangeChanged.connect(self._scroll_range_changed)
        self.verticalScrollBar().valueChanged.connect(self._scroll_value_changed)
        self.background=QPixmap();self.cover=QPixmap()
        self.setOpenLinks(False);self.setOpenExternalLinks(False)
        self.setStyleSheet('QTextBrowser { background: transparent; border: 1px solid #AFC8D3; border-radius: 7px; padding: 8px; color: #142B36; }')
        self.viewport().setAutoFillBackground(False)

    def set_background(self,path):
        self.background=QPixmap(str(path)) if path and Path(path).is_file() else QPixmap()
        self.update_cover()

    def update_cover(self):
        self.cover=self.background.scaled(self.viewport().size(),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation) if not self.background.isNull() else QPixmap()
        self.viewport().update()

    def resizeEvent(self,event):
        bar = self.verticalScrollBar()
        follow = self.latest_scroll.isActive() or bar.maximum() - bar.value() < 30
        self._follow_latest = follow
        super().resizeEvent(event);self.update_cover()
        if follow:
            self.latest_scroll.start(0)

    def show_latest_message(self):
        if self.isVisible():
            self._scrolling_latest = True
            try:
                self.document().documentLayout().documentSize()
                bar = self.verticalScrollBar()
                bar.setValue(bar.maximum())
            finally:
                self._scrolling_latest = False

    def _scroll_range_changed(self, minimum, maximum):
        # Scrollbar visibility can trigger a second text reflow after showing.
        if self._follow_latest and self.isVisible():
            self.latest_scroll.start(0)

    def _scroll_value_changed(self, value):
        if not self._scrolling_latest and not self.latest_scroll.isActive():
            self._follow_latest = self.verticalScrollBar().maximum() - value < 30

    def stop_following_latest(self):
        self._follow_latest = False
        self.latest_scroll.stop()

    def wheelEvent(self, event):
        self.stop_following_latest()
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        self.stop_following_latest()
        super().keyPressEvent(event)

    def paintEvent(self,event):
        painter=QPainter(self.viewport())
        if not self.cover.isNull():
            painter.drawPixmap((self.viewport().width()-self.cover.width())//2,(self.viewport().height()-self.cover.height())//2,self.cover)
        painter.end();super().paintEvent(event)

    def set_messages(self,messages,live=None):
        self.stop_sticker_movies()
        self.sticker_frames = {}
        self.messages=[dict(m) for m in messages][-100:]
        marker='bubble_'+uuid.uuid4().hex
        shown=[]
        for message in self.messages:
            parts = message.get('parts', [])
            if (message.get('role') == 'assistant' and self.sticker_catalog
                    and not self.assistant_markdown):
                parts = self.sticker_catalog.parts_for_message(message)
                if not parts:
                    # An old reply containing only an unresolvable annotation
                    # must not fall back to displaying its original raw text.
                    continue
            if parts and message.get('role') == 'assistant' and not self.assistant_markdown:
                for part in parts:
                    shown.append(dict(role='assistant', name=message.get('name'),
                                      content=part.get('text', ''),
                                      stickers=[part['id']] if part.get('type') == 'sticker' else []))
                shown[-1]['sources'] = message.get('sources', [])
            else:
                shown.append(message)
        shown += [dict(role='assistant',name=live[0],content=marker)] if live else []
        blocks=[]
        for m in shown:
            user=m.get('role')=='user'
            name=html.escape(str(m.get('name') or ('你' if user else '天依')))
            content=str(m.get('content',''))
            if self.assistant_markdown and m.get('role')=='assistant' and content!=marker:
                from .work_markdown import markdown_body
                body=markdown_body(content)
            else:
                body='<br>'+html.escape(content).replace('\n','<br>')
            for key in m.get('stickers', [])[:1]:
                item = self.sticker_catalog.get(key) if self.sticker_catalog else None
                if item is None:
                    body += '<br>[表情图片已不存在]'
                    continue
                pixmap = QPixmap(str(item.path))
                if max(pixmap.width(), pixmap.height()) > STICKER_DISPLAY_SIZE:
                    pixmap = pixmap.scaled(STICKER_DISPLAY_SIZE, STICKER_DISPLAY_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if pixmap.isNull():
                    body += '<br>[表情图片无法读取]'
                    continue
                self.sticker_frames[key] = pixmap
                body += (f'<br><img src="sticker:{key}" width="{pixmap.width()}" height="{pixmap.height()}" '
                         f'alt="{html.escape(item.title, quote=True)}">')
                if item.source.startswith(('https://', 'http://')):
                    body += '<br><a href="' + html.escape(item.source, quote=True) + '">图片来源</a>'
            from .lookup_protocol import sources_from_rows
            sources = sources_from_rows(m.get('sources', []))
            if sources:
                links = []
                for source in sources:
                    label = html.escape(source['title'])
                    links.append('<a href="' + html.escape(source['url'], quote=True) + '">' + label + '</a>' if source['url'] else label)
                body += '<br><br><small>查询来源：' + ' · '.join(links) + '</small>'
            bubble=f'<td width="84%"><b>{name}</b>{body}</td>'
            gap='<td width="16%"></td>'
            blocks.append('<table width="100%" cellspacing="0" cellpadding="10"><tr>'+ (gap+bubble if user else bubble+gap) +'</tr></table><p style="margin:4px"></p>')
        self.setHtml(''.join(blocks))
        # Only animate recent GIFs; old messages keep their first frame.
        gif_keys = [key for key in self.sticker_frames if self.sticker_catalog.get(key).animated][-8:]
        for key in gif_keys:
            item = self.sticker_catalog.get(key)
            movie = QMovie(str(item.path), parent=self)
            movie.setScaledSize(self.sticker_frames[key].size())
            movie.setCacheMode(QMovie.CacheNone)
            movie.frameChanged.connect(lambda _, k=key, m=movie: self._sticker_frame(k, m))
            self.sticker_movies[key] = movie
            movie.start()
            if not self.isVisible():
                movie.setPaused(True)
        tables=[f for f in self.document().rootFrame().childFrames() if isinstance(f,QTextTable)]
        for table,message in zip(tables,shown):
            user=message.get('role')=='user'
            cell=table.cellAt(0,1 if user else 0)
            fmt=cell.format().toTableCellFormat()
            fmt.setBackground(QBrush(QColor(207,235,249,185) if user else QColor(255,255,255,185)))
            cell.setFormat(fmt)
        self.live_start=self.live_end=None
        if live:
            cursor=self.document().find(marker)
            self.live_start=cursor.selectionStart();cursor.insertText(live[1])
            self.live_end=cursor.position()
        bar=self.verticalScrollBar();bar.setValue(bar.maximum())
        self._follow_latest = True
        if self.isVisible():
            self.latest_scroll.start(0)

    def loadResource(self, kind, name):
        if name.scheme() == 'sticker':
            return self.sticker_frames.get(name.path(), QPixmap())
        return super().loadResource(kind, name)

    def stop_sticker_movies(self):
        for movie in self.sticker_movies.values():
            movie.stop()
            movie.setFileName('')
            movie.deleteLater()
        self.sticker_movies = {}

    def _sticker_frame(self, key, movie):
        if self.sticker_movies.get(key) is not movie:
            return
        self.document().addResource(QTextDocument.ImageResource, QUrl('sticker:' + key), movie.currentPixmap())
        self.document().markContentsDirty(0, self.document().characterCount())
        self.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        # Hidden views have not settled their wrapped text / image geometry.
        # Follow layout changes until the reader chooses an older message.
        self._follow_latest = True
        self.latest_scroll.start(0)
        for movie in self.sticker_movies.values():
            movie.setPaused(False)

    def hideEvent(self, event):
        self.latest_scroll.stop()
        for movie in self.sticker_movies.values():
            movie.setPaused(True)
        super().hideEvent(event)

    def update_live(self,text):
        if self.live_start is None:return
        bar=self.verticalScrollBar();follow=bar.maximum()-bar.value()<30
        cursor=QTextCursor(self.document());cursor.setPosition(self.live_start)
        cursor.setPosition(self.live_end,QTextCursor.KeepAnchor);cursor.insertText(text)
        self.live_end=cursor.position()
        if follow:bar.setValue(bar.maximum())

    def createMimeDataFromSelection(self):
        data = super().createMimeDataFromSelection()
        if not self.assistant_markdown or '\ufffc' not in data.text():
            return data
        selection = self.textCursor()
        pos = selection.selectionStart()
        pieces = data.text().split('\ufffc')
        result = [pieces[0]]
        for piece in pieces[1:]:
            cursor = self.document().find('\ufffc', pos)
            if cursor.isNull() or cursor.selectionEnd() > selection.selectionEnd():
                return data
            fmt = cursor.charFormat()
            tex = fmt.property(QTextFormat.ImageAltText) if fmt.isImageFormat() else None
            result.extend((r'\(' + tex + r'\)' if tex else '\ufffc', piece))
            pos = cursor.selectionEnd()
        data.setText(''.join(result))
        return data

    def append_message(self,role,text,name=None):
        if not text:return
        if not self.messages and self.toPlainText().strip():
            self.messages=[dict(role='assistant',name='历史记录',content=self.toPlainText())]
        rows=self.messages+[dict(role=role,name=name or ('你' if role=='user' else '天依'),content=text)]
        while len(rows)>1 and sum(len(x.get('content','')) for x in rows)>60000:rows.pop(0)
        self.set_messages(rows)

    def appendPlainText(self,text):
        self.append_message('assistant',text)
