"""Selectable text bubbles with a locally stored, cover-cropped background."""
import html
import uuid
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QTextCursor, QTextTable, QBrush
from PySide6.QtWidgets import QTextBrowser
from deskpet.ui.background import save_background




class ConversationView(QTextBrowser):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.messages=[];self.live_start=None;self.live_end=None
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
        super().resizeEvent(event);self.update_cover()

    def paintEvent(self,event):
        painter=QPainter(self.viewport())
        if not self.cover.isNull():
            painter.drawPixmap((self.viewport().width()-self.cover.width())//2,(self.viewport().height()-self.cover.height())//2,self.cover)
        painter.end();super().paintEvent(event)

    def set_messages(self,messages,live=None):
        self.messages=[dict(m) for m in messages][-100:]
        marker='bubble_'+uuid.uuid4().hex
        shown=self.messages+([dict(role='assistant',name=live[0],content=marker)] if live else [])
        blocks=[]
        for m in shown:
            user=m.get('role')=='user'
            name=html.escape(str(m.get('name') or ('你' if user else '天依')))
            body=html.escape(str(m.get('content',''))).replace('\n','<br>')
            bubble=f'<td width="84%"><b>{name}</b><br>{body}</td>'
            gap='<td width="16%"></td>'
            blocks.append('<table width="100%" cellspacing="0" cellpadding="10"><tr>'+ (gap+bubble if user else bubble+gap) +'</tr></table><p style="margin:4px"></p>')
        self.setHtml(''.join(blocks))
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

    def update_live(self,text):
        if self.live_start is None:return
        bar=self.verticalScrollBar();follow=bar.maximum()-bar.value()<30
        cursor=QTextCursor(self.document());cursor.setPosition(self.live_start)
        cursor.setPosition(self.live_end,QTextCursor.KeepAnchor);cursor.insertText(text)
        self.live_end=cursor.position()
        if follow:bar.setValue(bar.maximum())

    def append_message(self,role,text,name=None):
        if not text:return
        if not self.messages and self.toPlainText().strip():
            self.messages=[dict(role='assistant',name='历史记录',content=self.toPlainText())]
        rows=self.messages+[dict(role=role,name=name or ('你' if role=='user' else '天依'),content=text)]
        while len(rows)>1 and sum(len(x.get('content','')) for x in rows)>60000:rows.pop(0)
        self.set_messages(rows)

    def appendPlainText(self,text):
        self.append_message('assistant',text)
