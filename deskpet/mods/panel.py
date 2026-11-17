"""Host-owned compact contribution area; optional packages supply commands only."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QMenu


class ModPanel(QWidget):
    def __init__(self,pet,parent=None):
        super().__init__(parent)
        self.pet=pet;self.signature=None
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setTextFormat(Qt.PlainText)
        box.addWidget(self.summary)
        self.row=QHBoxLayout();box.addLayout(self.row)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.refresh_visible);self.timer.start()
        self.refresh()

    def refresh_visible(self):
        # A hidden toolbar needs no polling of Mod summaries or their databases.
        # Use the parent: this row can be hidden because it currently has no Mods.
        if self.parentWidget() is None or self.parentWidget().isVisible():self.refresh()

    def refresh(self):
        host=getattr(self.pet,'mod_host',None)
        entries=host.services.panel_items() if host and hasattr(host,'services') else []
        self.setVisible(bool(entries))
        settings=self.pet.panel.settings
        self.summary.setVisible(settings.value('mods/panel_summary',True,type=bool))
        self.summary.setText('\n'.join(item[1] for item in entries))
        pinned=settings.value('mods/panel_pinned',None)
        if isinstance(pinned,str):pinned=[pinned]
        signature=(str(pinned),tuple((owner,tuple((k,v[0]) for k,v in actions.items())) for owner,_,actions in entries))
        if signature==self.signature:return
        self.signature=signature
        while self.row.count():
            item=self.row.takeAt(0)
            if item.widget():item.widget().deleteLater()
        actions=[(owner,key,value[0]) for owner,_,items in entries for key,value in items.items()]
        direct=actions[:2] if pinned is None else [a for a in actions if a[0]+':'+a[1] in pinned][:2]
        for owner,key,title in direct:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,o=owner,k=key:host.services.invoke(o,k))
            self.row.addWidget(button)
        if actions:
            more=QPushButton('更多互动');menu=QMenu(more)
            for owner,key,title in actions:
                if (owner,key,title) in direct:continue
                action=menu.addAction(title);action.triggered.connect(lambda checked=False,o=owner,k=key:host.services.invoke(o,k))
            menu.addSeparator();custom=menu.addMenu('调整主面板入口（最多两个）')
            selected=[a[0]+':'+a[1] for a in direct]
            for owner,key,title in actions:
                action=custom.addAction(title);action.setCheckable(True);identity=owner+':'+key;action.setChecked(identity in selected)
                action.triggered.connect(lambda checked,i=identity,s=selected:self.pin(i,checked,s))
            summary=menu.addAction('显示今日陪伴摘要');summary.setCheckable(True);summary.setChecked(settings.value('mods/panel_summary',True,type=bool))
            summary.triggered.connect(lambda checked:(settings.setValue('mods/panel_summary',checked),self.refresh()))
            more.setMenu(menu);self.row.addWidget(more)

    def pin(self,identity,checked,selected):
        values=[x for x in selected if x!=identity]
        if checked:values=(values+[identity])[-2:]
        self.pet.panel.settings.setValue('mods/panel_pinned',values);self.refresh()

    def showEvent(self,event):
        self.refresh();super().showEvent(event)
