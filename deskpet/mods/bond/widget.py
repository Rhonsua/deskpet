"""Small offline companion dashboard with an explicit performance entrance."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QImage, QPen
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QProgressBar,QPushButton,
    QApplication,QTabWidget,QTextBrowser,QLineEdit,QSpinBox,QFileDialog,QMessageBox,QInputDialog,QDialog,QComboBox,QCheckBox,QScrollArea,QFrame,QGridLayout)
from .store import STAGES,CATEGORIES
from .album import MemoryBook
from deskpet.ui.background import BackgroundSurface


def label(text):
    item=QLabel(text);item.setWordWrap(True);item.setTextFormat(Qt.PlainText)
    return item


class ThemeBanner(QFrame):
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(104,190,215,45),1))
        for size in (120,160,200):
            painter.drawEllipse(QRectF(self.width()-size/2-60,self.height()/2-size/2,size,size))
        painter.end()


class BookWindow(QDialog):
    def __init__(self,owner):
        super().__init__(None,Qt.Window|Qt.FramelessWindowHint)
        self.owner=owner;self.return_to_dashboard=False
        self.setObjectName('bookWindow');self.setAttribute(Qt.WA_TranslucentBackground,True)
        self.setStyleSheet('QDialog#bookWindow {background:transparent;}')
        self.setWindowTitle('天依 · 成长纪念集')
        self.content=QVBoxLayout(self);self.content.setContentsMargins(0,0,0,0)

    def closeEvent(self,event):
        self.owner._finish_book(self.return_to_dashboard)
        self.return_to_dashboard=False
        super().closeEvent(event)


class BondWidget(BackgroundSurface):
    def __init__(self,mod,parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QPalette
        self.dark = QApplication.palette().color(QPalette.Window).lightness() < 128
        self.surface_color='#152633' if self.dark else '#eaf5fa'
        self.surfaceReady.connect(self._surface_ready)
        self.set_surface(Path(__file__).parent/'assets'/'tianyi-background.webp')
        self.set_placement(mod.store.preference('background_position',dict(x=0,y=35,zoom=115)))
        from deskpet.ui.theme import apply_light_palette
        if not self.dark: apply_light_palette(self)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.mod=mod;self.source='';self.shown_stage=mod.store.stage
        self.analyzer=None;self.preparing=False;self.quiet_started=None
        self.setMinimumSize(560,500)
        style='''QWidget {background:#f5f9fc;color:#243b50;font:10pt "Microsoft YaHei UI";}
            QTabWidget::pane {border:1px solid #cfdfeb;background:#f5f9fc;border-radius:8px;}
            QFrame#hero {border:1px solid #d0e8ef;border-radius:12px;}
            QLabel {background:transparent;} QWidget#advancedContent {background:transparent;} QFrame#card {background:#fffdf9;border:1px solid #d8e9ef;border-radius:12px;} QFrame#activityCard {background:#f4fafc;border:1px solid #e1edf1;border-radius:8px;} QFrame#activityCard QPushButton {padding:4px 8px;} QScrollArea {border:0;background:#f5f9fc;} QWidget#homeContent {background:#f5f9fc;} QTabBar::tab {background:#e4f0f6;color:#365c6e;padding:7px 12px;border-radius:5px;} QTabBar::tab:selected {background:#c7e5ee;color:#174b63;}
            QLineEdit,QTextBrowser,QSpinBox,QComboBox {background:#fff;color:#243b50;border:1px solid #c3d7e5;border-radius:6px;padding:7px;}
            QPushButton {background:#e5f1fa;color:#1f536b;border:1px solid #c1dce9;border-radius:8px;padding:9px;}
            QComboBox QAbstractItemView {background:#fffdf9;color:#243b50;selection-background-color:#c7e5ee;selection-color:#174b63;}
            QCheckBox {background:transparent;color:#243b50;spacing:6px;}
            QCheckBox::indicator {width:15px;height:15px;background:#fff;border:1px solid #9dbdce;border-radius:3px;}
            QCheckBox::indicator:checked {background:#67b5ce;}
            QWidget:disabled {color:#788d99;} QLabel:disabled {color:#788d99;}
            QScrollArea > QWidget > QWidget {background:#f5f9fc;}
            QPushButton#primary {background:#287b99;color:white;font-weight:bold;padding:10px 22px;} QPushButton#primary:hover {background:#438fae;} QPushButton:hover {background:#d2eaf6;} QPushButton:disabled {color:#8295a2;}
            QProgressBar {background:#dce8ee;border:0;border-radius:3px;height:6px;}
            QProgressBar::chunk {background:#78b9bf;border-radius:3px;}'''
        if self.dark:
            colors={'#ddf4fb':'#284a59','#cce9f3':'#1f3f51','#eff8f9':'#183240','#c4e3ed':'#446573','#edf8fc':'#203a48','#d5edf5':'#294d5c','#d0e8ef':'#43636e','#f5f9fc':'#152633','#243b50':'#e4f0f4','#cfdfeb':'#36505c','#fffdf9':'#203744',
                '#d8e9ef':'#395561','#f4fafc':'#29414d','#e1edf1':'#3b5661','#e4f0f6':'#263e4b',
                '#365c6e':'#d2e4e9','#c7e5ee':'#3d6472','#174b63':'#f2fbfd','#c3d7e5':'#58717c',
                '#e5f1fa':'#29424e','#1f536b':'#e0eff2','#c1dce9':'#496570','#9dbdce':'#7f9ea9',
                '#67b5ce':'#75c5dc','#788d99':'#a4b7bd','#8295a2':'#a4b7bd','#287b99':'#83cbe0',
                '#438fae':'#a2d9e8','#d2eaf6':'#385766','#dce8ee':'#35505c','#78b9bf':'#83cbe0',
                '#fff':'#1a303c','color:white':'color:#102c39'}
            for old in sorted(colors,key=len,reverse=True):style=style.replace(old,colors[old])
        # The window owns one continuous picture. Scroll viewports and page
        # containers must stay transparent; only reading/interaction surfaces tint it.
        card='rgba(18,39,53,220)' if self.dark else 'rgba(255,253,249,213)'
        hero='rgba(19,43,58,220)' if self.dark else 'rgba(244,252,255,220)'
        inner='rgba(34,63,77,180)' if self.dark else 'rgba(239,250,255,170)'
        style += f'''
            QWidget {{background:transparent;}}
            QTabWidget::pane {{border:0;background:transparent;}}
            QScrollArea,QStackedWidget,QScrollArea > QWidget > QWidget,QWidget#homeContent {{background:transparent;border:0;}}
            QFrame#hero {{background:{hero};}}
            QFrame#card {{background:{card};}}
            QFrame#activityCard {{background:{inner};}}
            QLabel#footer {{background:{hero};padding:6px 10px;border-radius:6px;}}
        '''
        self.setStyleSheet(style)
        palette=self.palette()
        palette.setColor(QPalette.PlaceholderText,QColor('#a6bac2' if self.dark else '#667d89'))
        self.setPalette(palette)
        layout=QVBoxLayout(self);self.outer_layout=layout;layout.setContentsMargins(16,14,16,12);layout.setSpacing(8)
        hero=ThemeBanner();self.hero=hero;hero.setObjectName('hero');hero_row=QHBoxLayout(hero);hero_row.setContentsMargins(16,10,12,10);hero_row.setSpacing(12)
        hero_text=QVBoxLayout();hero_text.setSpacing(5);hero_row.addLayout(hero_text,1)
        self.heading=label('');self.heading.setStyleSheet('font-size:16pt;font-weight:bold;color:'+('#b3e1ef' if self.dark else '#24586c')+';');hero_text.addWidget(self.heading)
        self.detail=label('');hero_text.addWidget(self.detail)
        self.progress=QProgressBar();self.progress.setTextVisible(False);self.progress.setFixedHeight(6);hero_text.addWidget(self.progress)
        adjust=QPushButton('调整背景');self.adjust_button=adjust;adjust.clicked.connect(self.adjust_background)
        adjust.setEnabled(not self.surface_image.isNull());hero_row.addWidget(adjust,0,Qt.AlignTop)
        layout.addWidget(hero)
        self.content_row=QHBoxLayout();self.content_row.setSpacing(0);layout.addLayout(self.content_row,1)
        self.tabs=QTabWidget();self.content_row.addWidget(self.tabs,1)

        home=QScrollArea();home.setWidgetResizable(True);home.setFrameShape(QFrame.NoFrame);self.tabs.addTab(home,'今天的陪伴')
        home_content=QWidget();home_content.setObjectName('homeContent');home.setWidget(home_content);box=QVBoxLayout(home_content)
        box.setContentsMargins(12,12,12,12);box.setSpacing(10)
        intro=QFrame();intro.setObjectName('card');intro_box=QVBoxLayout(intro)
        title=label('今天，和天依一起');title.setStyleSheet('font-size:15pt;font-weight:bold;color:'+('#b3e1ef' if self.dark else '#286985')+';');intro_box.addWidget(title)
        intro_box.addWidget(label('每类互动每天记录一次 · 最多 +50 亲密度，忙碌或离线也不会扣分'))
        self.recommendation=label('');intro_box.addWidget(self.recommendation)
        self.need=label('');intro_box.addWidget(self.need)
        need_actions=QHBoxLayout();self.defer_need=QPushButton('稍后');self.quiet_needs=QPushButton('今天先安静')
        self.defer_need.setToolTip('暂停小心愿提醒 30 分钟，今天不重复刚才的心愿');self.quiet_needs.setToolTip('今天不再主动提小心愿，不影响聊天或其他通知')
        self.defer_need.clicked.connect(lambda:self.defer_wish(False));self.quiet_needs.clicked.connect(lambda:self.defer_wish(True))
        need_actions.addWidget(self.defer_need);need_actions.addWidget(self.quiet_needs);need_actions.addStretch();intro_box.addLayout(need_actions);box.addWidget(intro)
        daily=QFrame();daily.setObjectName('card');daily_box=QVBoxLayout(daily)
        self.daily_title=label('今日互动');self.daily_title.setStyleSheet('font-weight:bold;font-size:12pt;');daily_box.addWidget(self.daily_title)
        self.checklist=label('');self.checklist.hide();daily_box.addWidget(self.checklist)
        grid=QGridLayout();grid.setSpacing(8);daily_box.addLayout(grid)
        self.category_status={}
        specs=[('headpat','摸摸头','打开控制',lambda:self.present_host('control')),
               ('feed','照料 / 投喂','选择点心',lambda:self.present_host('food')),
               ('chat','说说话','打开聊天',lambda:self.present_host('chat')),
               ('listen','听歌 / 安静陪伴','打开歌单',lambda:self.present_host('music')),
               ('game','演出 / 猜歌','去演出',lambda:self.tabs.setCurrentIndex(1))]
        for index,(key,title,caption,action) in enumerate(specs):
            card=QFrame();card.setObjectName('activityCard');card_box=QVBoxLayout(card);card_box.setContentsMargins(10,8,10,8);card_box.setSpacing(4)
            self.category_status[key]=label('');card_box.addWidget(self.category_status[key])
            button=QPushButton(caption);button.clicked.connect(action);card_box.addWidget(button)
            if key=='feed':
                care=QPushButton('吃饱后歇歇');care.clicked.connect(self.care);card_box.addWidget(care)
            if key=='chat':
                self.diary=QPushButton('写一句话');self.diary.clicked.connect(self.write_diary);card_box.addWidget(self.diary)
            if key=='listen':
                self.quiet=QPushButton('开启 10 分钟安静陪伴');self.quiet.clicked.connect(self.quiet_time);card_box.addWidget(self.quiet)
            grid.addWidget(card,index//2,index%2)
        box.addWidget(daily);box.addStretch()
        play=QWidget();playbox=QVBoxLayout(play);playbox.setContentsMargins(12,12,12,12);playbox.setSpacing(12);self.tabs.addTab(play,'节奏演出')
        def section(title):
            frame=QFrame();frame.setObjectName('card');layout=QVBoxLayout(frame);layout.setContentsMargins(14,12,14,12);layout.setSpacing(8)
            heading=label(title);heading.setStyleSheet('font-size:12pt;font-weight:bold;color:'+('#b3e1ef' if self.dark else '#286985')+';');layout.addWidget(heading);playbox.addWidget(frame)
            return layout
        songbox=section('歌曲');self.song=label('当前：无音乐节拍练习');songbox.addWidget(self.song)
        actions=QHBoxLayout()
        choose=QPushButton('选择本地 MP3');choose.clicked.connect(self.choose);actions.addWidget(choose)
        current=QPushButton('使用当前歌曲');current.clicked.connect(self.current);actions.addWidget(current)
        practice=QPushButton('节拍练习');practice.clicked.connect(lambda:self.select(''));actions.addWidget(practice)
        actions.addStretch();songbox.addLayout(actions)
        options=section('演出设置');grid=QGridLayout();grid.setSpacing(8);options.addLayout(grid)
        self.difficulty=QComboBox()
        for caption,key in [('入门','easy'),('标准','normal'),('进阶','hard')]:self.difficulty.addItem(caption,key)
        self.chart_mode=QComboBox();self.chart_mode.addItems(['花样演出','标准挑战'])
        self.input_mode=QComboBox();self.input_mode.addItems(['键盘三轨','键盘四轨','鼠标单手'])
        self.duration=QComboBox()
        for seconds in (30,45,60):self.duration.addItem(f'{seconds} 秒',seconds)
        self.duration.setCurrentIndex(1)
        for i,(caption,control) in enumerate([('难度',self.difficulty),('编排',self.chart_mode),('操作方式',self.input_mode),('演出时长',self.duration)]):
            grid.addWidget(label(caption),i//2,(i%2)*2);grid.addWidget(control,i//2,(i%2)*2+1)
        advanced=QPushButton('高级设置');advanced.setCheckable(True);options.addWidget(advanced,0,Qt.AlignLeft)
        advanced_content=QWidget();advanced_content.setObjectName('advancedContent');adv=QGridLayout(advanced_content);adv.setContentsMargins(0,0,0,0)
        self.bpm=QSpinBox();self.bpm.setRange(50,200);self.bpm.setValue(120);adv.addWidget(label('练习 BPM'),0,0);adv.addWidget(self.bpm,0,1)
        self.auto_clip=QCheckBox('自动选择片段');self.auto_clip.setChecked(True);adv.addWidget(self.auto_clip,1,0)
        self.clip_offset=QSpinBox();self.clip_offset.setRange(0,21600);self.clip_offset.setSuffix(' 秒开始');adv.addWidget(self.clip_offset,1,1)
        advanced_content.hide();advanced.toggled.connect(advanced_content.setVisible);options.addWidget(advanced_content)
        startrow=QHBoxLayout();self.start=QPushButton('准备并进入演出');self.start.setObjectName('primary');self.start.clicked.connect(self.play);startrow.addWidget(self.start)
        self.cancel=QPushButton('取消分析');self.cancel.setEnabled(False);self.cancel.hide();self.cancel.clicked.connect(self.cancel_analysis);startrow.addWidget(self.cancel);startrow.addStretch();playbox.addLayout(startrow)
        savedbox=section('收藏谱');savedrow=QHBoxLayout();self.saved=QComboBox();savedrow.addWidget(self.saved,1)
        replay=QPushButton('重玩选中的收藏谱');replay.clicked.connect(self.replay);savedrow.addWidget(replay);savedbox.addLayout(savedrow)
        self.best=label('');savedbox.addWidget(self.best);playbox.addStretch()
        album=QWidget();al=QVBoxLayout(album);al.setContentsMargins(0,0,0,0);self.tabs.addTab(album,'成长纪念集')
        self.album_page=album;self.album_layout=al;self._book_window=None;self._book_origin=None
        self.album=MemoryBook(mod.store, defer=True);al.addWidget(self.album,1)
        self.album.back_requested.connect(self._return_from_book)
        self.album.close_requested.connect(self._close_book)
        self.album.export_requested.connect(self.export_card)
        settings=QWidget();sl=QVBoxLayout(settings);sl.setContentsMargins(12,12,12,12);sl.setSpacing(10);self.tabs.addTab(settings,'舞台与纪念')
        def settings_section(title):
            frame=QFrame();frame.setObjectName('card');box=QVBoxLayout(frame);box.setContentsMargins(14,12,14,12)
            heading=label(title);heading.setStyleSheet('font-size:12pt;font-weight:bold;color:'+('#b3e1ef' if self.dark else '#286985')+';');box.addWidget(heading);sl.addWidget(frame);return box
        identity=settings_section('我们的称呼')
        row=QHBoxLayout();self.nickname=QLineEdit();self.nickname.setPlaceholderText('熟悉后可设定专属称呼（最多 20 字）');self.nickname.setMaxLength(20)
        self.nickname.setText(mod.store.value['nickname']);row.addWidget(self.nickname)
        self.save_name=QPushButton('记住称呼');self.save_name.clicked.connect(self.rename);row.addWidget(self.save_name);identity.addLayout(row)
        self.ceremony=QPushButton('看看我们的阶段纪念');self.ceremony.clicked.connect(self.show_stage);identity.addWidget(self.ceremony,0,Qt.AlignLeft)
        stagebox=settings_section('演出舞台')
        stagebox.addWidget(label('用于「节奏演出」与「三曲小演出」。先看场景预览，再选择启用。'))
        row=QHBoxLayout();self.theme=QComboBox()
        for title,key in [('阶段默认舞台 · 免费',''),('海底回响 · 60 音符','ocean'),('花间小调 · 100 音符','sakura'),('星光剧院 · 150 音符','gold')]:self.theme.addItem(title,key)
        self.theme.setCurrentIndex(max(0,self.theme.findData(mod.store.preference('theme',''))))
        row.addWidget(self.theme,1);self.buy_stage=QPushButton('获得并使用');self.buy_stage.clicked.connect(self.buy_theme);row.addWidget(self.buy_stage);stagebox.addLayout(row)
        from .stage_art import StagePreview
        self.stage_preview=StagePreview();self.stage_preview.setMinimumHeight(145);stagebox.addWidget(self.stage_preview)
        self.stage_description=label('');stagebox.addWidget(self.stage_description)
        self.theme.currentIndexChanged.connect(self.preview_theme);self.preview_theme()
        stagebox.addWidget(label('只在点击「获得并使用」时购买；已拥有的舞台不会重复扣费。'))
        preferences=settings_section('陪伴偏好');row=QHBoxLayout();row.addWidget(label('每日小心愿上限'))
        self.needs=QSpinBox();self.needs.setRange(0,5);self.needs.setValue(mod.store.preference('needs_per_day',3));row.addWidget(self.needs);row.addStretch();preferences.addLayout(row)
        self.needs.valueChanged.connect(lambda value:mod.store.configure('needs_per_day',value))
        row=QHBoxLayout();self.birthday=QLineEdit(mod.store.preference('birthday',''));self.birthday.setPlaceholderText('可选生日，例如 06-15；留空不记录');row.addWidget(self.birthday)
        save_birthday=QPushButton('保存生日');save_birthday.clicked.connect(self.save_birthday);row.addWidget(save_birthday);preferences.addLayout(row)
        row=QHBoxLayout();favorite=QPushButton('喜欢当前歌曲');favorite.clicked.connect(self.favorite_song);row.addWidget(favorite)
        tired=QPushButton('今天有些累');tired.clicked.connect(lambda:self.add_fact('tired','用户明确表示今天有些累'));row.addWidget(tired)
        forget=QPushButton('管理偏好与记录');forget.clicked.connect(self.manage_facts);row.addWidget(forget);row.addStretch();preferences.addLayout(row)
        sl.addStretch()
        for index, content in ((1, play), (3, settings)):
            caption=self.tabs.tabText(index);self.tabs.removeTab(index)
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame);scroll.setWidget(content)
            self.tabs.insertTab(index,scroll,caption)
        self.note=label('所有记录保存在本机。停用扩展保留纪念册，并恢复原成长显示。');self.note.setObjectName('footer');layout.addWidget(self.note)
        self.refresh_timer=QTimer(self);self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(lambda:self.refresh() if self.isVisible() and self.tabs.currentIndex()==0 else None)
        self._charts_revision=None
        self.tabs.currentChanged.connect(self._tab_changed)
        self.refresh()

    def _surface_ready(self,ready):
        if hasattr(self,'adjust_button'):self.adjust_button.setEnabled(ready)
        if hasattr(self,'content_row') and hasattr(self,'tabs'):self._background_spacing()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'content_row'):self._background_spacing()

    def _background_spacing(self):
        # Let the actual full-window artwork breathe, without a portrait sidebar.
        space=min(250,round(self.width()*.28)) if self.width()>=840 and self.tabs.currentIndex()!=2 and not self.surface_image.isNull() else 0
        self.content_row.setContentsMargins(0,0,space,0)

    def paintEvent(self,event):
        if hasattr(self,'tabs') and self.tabs.currentIndex()==2:
            painter=QPainter(self)
            painter.fillRect(self.rect(),QColor('#172027' if self.dark else '#e8e7e1'))
            painter.end()
            return
        super().paintEvent(event)
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor(9,26,40,100) if self.dark else QColor(241,250,255,20))
        painter.end()

    def adjust_background(self):
        from deskpet.ui.background_position import BackgroundPositionDialog
        dialog=BackgroundPositionDialog(self)
        dialog.setWindowTitle('调整养成页背景')
        try:
            if dialog.exec()==QDialog.Accepted:
                self.mod.store.configure('background_position',self.surface_placement.as_dict())
        finally:dialog.deleteLater()

    def _open_book(self):
        if self._book_window and self._book_window.isVisible():
            self._book_window.raise_();self._book_window.activateWindow();return
        self._book_origin=self.window()
        book=BookWindow(self);self._book_window=book
        self.album_layout.removeWidget(self.album);self.album.setParent(book);book.content.addWidget(self.album)
        self.album.reload()
        screen=self._book_origin.screen().availableGeometry()
        book.resize(min(1000,screen.width()-30),min(800,screen.height()-30))
        book.move(screen.center()-book.rect().center())
        if hasattr(self.mod,'games'):self.mod.games.append(book)
        self._book_origin.hide();book.show();book.raise_();book.activateWindow()

    def _return_from_book(self):
        if self._book_window:
            self._book_window.return_to_dashboard=True;self._book_window.close()

    def _close_book(self):
        if self._book_window:self._book_window.close()

    def _finish_book(self,return_to_dashboard):
        book=self._book_window
        if book is None:return
        book.content.removeWidget(self.album);self.album.setParent(self.album_page);self.album_layout.addWidget(self.album)
        self._book_window=None
        self.tabs.setCurrentIndex(0)
        origin=self._book_origin;self._book_origin=None
        if return_to_dashboard and origin and self.mod.active:
            origin.show();origin.raise_();origin.activateWindow()
        if hasattr(self.mod,'games') and book in self.mod.games:self.mod.games.remove(book)
        book.deleteLater()

    def _tab_changed(self,index):
        if index==2:
            self._open_book();return
        self.hero.show();self.note.show();self.tabs.tabBar().show()
        self.outer_layout.setContentsMargins(16,14,16,12)
        self._background_spacing();self.update()
        if self.isVisible():self.refresh()

    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'refresh_timer'):
            self.refresh_timer.start();self.refresh()

    def hideEvent(self,event):
        if hasattr(self,'refresh_timer'):self.refresh_timer.stop()
        self.cancel_analysis()
        super().hideEvent(event)

    def refresh(self):
        if not self.mod.active:return
        store=self.mod.store;projection=store.projection();stage=store.stage
        self.heading.setText(f'{STAGES[stage][0]} · {store.value["nickname"] or "和天依的一点一滴"}')
        self.progress.setRange(0,projection['xp_goal']);self.progress.setValue(projection['xp'])
        self.detail.setText(f'亲密度 {store.value["affinity"]} · '+(f'距「{STAGES[stage+1][0]}」还差 {STAGES[stage+1][1]-store.value["affinity"]}' if stage<5 else '已经相伴，新的回忆仍会继续。')+(f'\n下一阶段解锁：{STAGES[stage+1][2]}' if stage<5 else ''))
        done=store.daily();self.daily_title.setText(f'今日互动  ·  {len(done)} / {len(CATEGORIES)}');self.checklist.setText('\n'.join(('✓ ' if k in done else '○ ')+v+(' · 已记录' if k in done else '') for k,v in CATEGORIES.items()))
        for key,title in CATEGORIES.items():
            self.category_status[key].setText(('✓ ' if key in done else '○ ')+title+(' · 已记录' if key in done else ''))
        if 'headpat' not in done:self.recommendation.setText('今天可以先摸摸头，打个招呼。')
        elif 'chat' not in done:self.recommendation.setText('想说话时，可以聊聊天或写下一句话。')
        elif len(done)<len(CATEGORIES):self.recommendation.setText('挑一件喜欢的事，慢慢陪伴就好。')
        else:self.recommendation.setText('今天的陪伴都已记录，安心休息吧。')
        if 'listen' not in done:
            elapsed=min(600,int(store.listen_seconds()))
            self.checklist.setText(self.checklist.text()+f'\n听歌进度 {elapsed//60}:{elapsed%60:02d} / 10:00')
            self.category_status['listen'].setText(f'○ 听歌 / 安静陪伴 · {elapsed//60}:{elapsed%60:02d} / 10:00')
        self.nickname.setEnabled(stage>=1);self.save_name.setEnabled(stage>=1)
        if self.isVisible() and self.tabs.currentIndex()==2:self.album.reload()
        self.best.setText('每份谱面独立保存成绩；新谱结算显示同谱最佳。')
        self.need.setText(self.mod.events.summary())
        wish_active=bool(getattr(self.mod.events,'active',None))
        self.defer_need.setVisible(wish_active);self.quiet_needs.setVisible(wish_active)
        if self.tabs.currentIndex()==1:
            revision=store.revision('charts')
            if revision != self._charts_revision:
                current=self.saved.currentData();self.saved.blockSignals(True);self.saved.clear()
                for key,chart in store.favorite_chart_summaries():self.saved.addItem((Path(chart['source']).stem or '离线练习')+' · '+chart['difficulty']+' · '+key[:6],key)
                index=self.saved.findData(current)
                if index>=0:self.saved.setCurrentIndex(index)
                self.saved.blockSignals(False);self._charts_revision=revision
        if self.quiet_started is not None:
            import time
            remaining=max(0,600-int(time.monotonic()-self.quiet_started))
            self.quiet.setText(f'安静陪伴剩余 {remaining//60}:{remaining%60:02d} · 点击取消' if remaining else '安静陪伴完成，点击收下今天的记录')
        if stage>self.shown_stage:
            self.shown_stage=stage
            self.note.setText(f'新的关系阶段：{STAGES[stage][0]}！点击“阶段纪念”一起庆祝。')
            # Remain in the user-opened widget; never interrupt work with a popup.
            if self.isVisible():self.show_stage()

    def present_host(self,destination):
        present=getattr(self.mod.services,'present',None)
        if not callable(present) or not present(destination):
            self.note.setText('请从桌宠原控制面板打开对应功能。')

    def defer_wish(self,today):
        defer=getattr(self.mod.events,'defer',None)
        if callable(defer) and defer(today=today):
            self.note.setText('今天先不提小心愿啦，想玩时再来。' if today else '小心愿先收好，至少 30 分钟内不再提醒。')
        self.refresh()

    def write_diary(self):
        text,ok=QInputDialog.getText(self,'说说今天','写一句想对天依说的话（只保存到本机纪念册，不调用 AI）：')
        if not ok or len(text.strip())<2:return
        now=datetime.now()
        with self.mod.store.db:
            self.mod.store.card('diary:'+now.date().isoformat(),'今天想说的话',text.strip()[:240],now)
        self.mod.event('chat',{})
        self.note.setText('记下来啦。今天的事情，慢慢和我说就好。')
        self.refresh()

    def rename(self):
        if self.mod.store.stage>=1:self.mod.store.nickname(self.nickname.text());self.refresh()

    def select(self,path):
        if self.preparing:self.cancel_analysis()
        self.source=path;self.song.setText('当前：'+(Path(path).stem if path else '无音乐节拍练习'))

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'选择演出歌曲','','MP3 音乐 (*.mp3)')
        if path:self.select(path)

    def current(self):
        path=self.mod.services.snapshot()['local_path']
        if path and Path(path).is_file():self.select(path)
        else:self.note.setText('当前不是可用的本地歌曲，请选择本地 MP3 或离线练习。')

    def play(self):
        if self.preparing:return
        other=self.mod.analysis_owner
        if other is not None and other is not self:
            import shiboken6
            if shiboken6.isValid(other) and other.preparing:
                self.note.setText('另一个演出页面正在分析，请等待完成或先取消。');return
        from .rhythm import RhythmGame
        for game in list(self.mod.games):
            try:
                if isinstance(game,RhythmGame) and game.isVisible():game.raise_();return
            except RuntimeError:pass
        if self.source:
            try:
                from mutagen import File
                info=File(self.source)
                if info is None or not info.info or info.info.length<35:raise ValueError('歌曲需至少 35 秒')
                self.song_length=info.info.length
                if self.analyzer is None:
                    self.analyzer=self.mod.services.analysis(self)
                    self.mod.analyzers.append(self.analyzer)
                    self.analyzer.changed.connect(lambda:self.note.setText(self.analyzer.status+f' {self.analyzer.progress}%') if self.preparing else None)
                    self.analyzer.analysisFinished.connect(self.analyzed)
                self.analyzer.set_source('')
                self.analyzer.set_source('local:'+str(Path(self.source).absolute()))
                if self.analyzer.analysis.get('features_version')==2:self.launch(self.analyzer.analysis);return
                self.preparing=True;self.mod.analysis_owner=self;self.start.setEnabled(False);self.cancel.setEnabled(True);self.cancel.show();self.analyzer.analyze()
            except Exception as error:self.note.setText('无法准备这首歌曲：'+str(error)[:180]);self.cancel_analysis()
        else:self.launch({})

    def analyzed(self,success):
        if not self.preparing or not self.mod.active:return
        if self.mod.analysis_owner is self:self.mod.analysis_owner=None
        self.preparing=False;self.start.setEnabled(True);self.cancel.setEnabled(False);self.cancel.hide()
        if success:
            self.trim_analysis_cache()
            self.launch(self.analyzer.analysis)
        elif QMessageBox.question(self,'节拍分析未完成','要使用清楚标记为练习的 BPM 谱面吗？')==QMessageBox.Yes:self.launch({})

    def cancel_analysis(self):
        if self.mod.analysis_owner is self:self.mod.analysis_owner=None
        self.preparing=False;self.start.setEnabled(True);self.cancel.setEnabled(False);self.cancel.hide()
        if self.analyzer:self.analyzer.cancel()

    def launch(self,analysis):
        import hashlib,secrets
        from .chart import generate,digest
        duration=float(self.duration.currentData());offset=0.
        identity='practice'
        if self.source:
            path=Path(self.source);stat=path.stat();identity=f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'
            duration=min(duration,self.song_length-4)
            offset=min(self.song_length-duration-1,self.song_length*.3 if self.auto_clip.isChecked() else self.clip_offset.value())
            if self.auto_clip.isChecked():
                peaks=analysis.get('onsets_ms',[])
                if peaks:
                    candidates=range(0,max(1,int(self.song_length-duration)),max(5,int(duration/2)))
                    offset=float(max(candidates,key=lambda t:sum(t+2<=x/1000<=t+duration-1 for x in peaks)))
        seed=(secrets.randbits(32) if self.chart_mode.currentIndex()==0 else int(hashlib.sha256((identity+str(offset)+self.difficulty.currentData()+self.input_mode.currentText()).encode()).hexdigest()[:8],16))
        chart=generate(analysis,source=self.source,offset=offset,duration=duration,bpm=analysis.get('bpm',self.bpm.value()),
            difficulty=self.difficulty.currentData(),lanes=4 if self.input_mode.currentIndex()==1 else 3,
            input_mode='mouse' if self.input_mode.currentIndex()==2 else 'keyboard',seed=seed)
        if self.source and analysis and chart['practice']:
            if QMessageBox.question(self,'片段拍点不足','这个片段没有可靠拍点。是否改用清楚标记的 BPM 练习谱？选择“否”可更换片段。')!=QMessageBox.Yes:return
        chart['audio_identity']=identity;chart['id']=digest(chart)
        self.mod.store.save_chart(chart);self.launch_chart(chart)

    def trim_analysis_cache(self):
        # Only generated files in this Mod's own analysis directory are evicted.
        if not self.analyzer:return
        directory=self.analyzer.directory.resolve()
        files=sorted(directory.glob('analysis-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        size=0
        for index,path in enumerate(files):
            if path.is_symlink() or path.resolve().parent!=directory:continue
            size+=path.stat().st_size
            if index>=100 or size>100*1024*1024:
                try:path.unlink()
                except OSError:pass

    def launch_chart(self,chart):
        from .rhythm import RhythmGame
        try:
            source=chart['source']
            if source:
                path=Path(source);stat=path.stat();identity=f'{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'
                if chart.get('audio_identity',identity)!=identity:raise ValueError('歌曲已修改，请重新准备谱面')
            game=RhythmGame(self.mod,source,parent=self,chart=chart)
        except Exception as error:self.note.setText('演出无法打开：'+str(error)[:180]);return
        self.mod.games.append(game);game.completed.connect(self.refresh);game.show()

    def replay(self):
        key=self.saved.currentData()
        if key:self.launch_chart(self.mod.store.chart(key))

    def care(self):
        if self.mod.services.snapshot()['hunger']<95:self.note.setText('还没吃饱，可以从原控制面板投喂。');return
        before=self.mod.store.stage;self.mod.store.award('feed');self.mod.after_growth(before);self.note.setText('吃饱就歇歇，今天的照料记下了。')

    def quiet_time(self):
        import time
        if self.quiet_started is None:self.quiet_started=time.monotonic()
        elif time.monotonic()-self.quiet_started>=600:
            before=self.mod.store.stage;self.mod.store.award('listen');self.mod.after_growth(before);self.quiet_started=None;self.quiet.setText('开启 10 分钟安静陪伴')
        else:self.quiet_started=None;self.quiet.setText('开启 10 分钟安静陪伴')
        self.refresh()

    def buy_theme(self):
        key=self.theme.currentData()
        if not key:success,message=True,'使用阶段默认舞台'
        else:success,message=self.mod.services.buy(key)
        if success:self.mod.store.configure('theme',key)
        self.note.setText(message)

    def preview_theme(self):
        key=self.theme.currentData() or ''
        self.stage_preview.set_scene(key,self.mod.store.stage)
        self.stage_description.setText({
            '':'随关系阶段变化的基础灯光舞台，无需花费音符。',
            'ocean':'海底回响：流动水波、上升气泡和水下光束。',
            'sakura':'花间小调：花枝、飘落花瓣和柔和的粉紫灯光。',
            'gold':'星光剧院：两侧帷幕、交错聚光灯和金色星光。',
        }[key])

    def save_birthday(self):
        value=self.birthday.text().strip()
        try:
            if value:value=datetime.strptime('2000-'+value,'%Y-%m-%d').strftime('%m-%d')
        except ValueError:self.note.setText('生日请按 月-日 填写，例如 06-15。');return
        self.mod.store.configure('birthday',value);self.note.setText('生日已保存；留空时不记录生日。')

    def add_fact(self,kind,value):
        self.mod.store.fact(kind,value);self.note.setText('只在本机记下了，可以随时查看或删除。')

    def favorite_song(self):
        path=self.mod.services.snapshot()['local_path']
        if path:self.add_fact('favorite',Path(path).stem)
        else:self.note.setText('请先选择一首本地歌曲。')

    def manage_facts(self):
        facts=[dict(row) for row in self.mod.store.db.execute('SELECT * FROM facts ORDER BY at DESC')]
        if not facts:self.note.setText('还没有主动保存的偏好或近期记录。');return
        items=[f'{row["at"][:10]} · {row["value"]}' for row in facts]
        text,ok=QInputDialog.getItem(self,'本地记忆','选择要删除的记录：',items,0,False)
        if ok:self.mod.store.forget(facts[items.index(text)]['id']);self.note.setText('已删除这条本地事实。')

    def show_stage(self):
        stage=self.mod.store.stage
        dialog=QDialog(self);dialog.setWindowTitle('我们的阶段纪念');dialog.setAttribute(Qt.WA_DeleteOnClose)
        box=QVBoxLayout(dialog)
        title=label('✦ '+STAGES[stage][0]+' ✦');title.setStyleSheet('font-size:24pt;font-weight:bold;color:#24586c;');box.addWidget(title)
        box.addWidget(label(['这份相遇，我会好好珍惜。','已经慢慢熟悉你在身边的感觉了。','你留下的小事，我会认真收好。','和你相处，越来越有默契了。','那些普通的日子，也会闪闪发光呢。','以后也一起慢慢走，好不好？'][stage]))
        box.addWidget(label('本阶段开放：'+STAGES[stage][2]))
        close=QPushButton('把这一刻收好');close.clicked.connect(dialog.accept);box.addWidget(close)
        self.mod.services.act('wave')
        for delay,action in [(2400,'turn'),(4800,'celebrate')]:
            QTimer.singleShot(delay,dialog,lambda a=action: self.mod.services.act(a) if self.mod.active and dialog.isVisible() else None)
        dialog.resize(440,240);dialog.show()

    def weekly(self):
        if self.mod.store.stage<2:return
        self.album.set_section('week');self.tabs.setCurrentIndex(2)

    def export_card(self):
        import json
        store=self.mod.store;options=['阶段纪念']
        if store.stage>=2:options.insert(0,'本周回忆')
        show=store.db.execute('SELECT body,at FROM shows ORDER BY at DESC LIMIT 1').fetchone()
        if show:options.insert(0,'最近的三曲演出')
        choice,ok=QInputDialog.getItem(self,'导出纪念卡','选择内容：',options,0,False)
        if not ok:return
        title=choice+' · '+STAGES[store.stage][0]
        if choice=='本周回忆':body=store.weekly()
        elif choice=='最近的三曲演出':body=show['at'][:10]+'\n\n'+'\n\n'.join(f'{i+1}. {item["title"]}' for i,item in enumerate(json.loads(show['body'])))
        else:body='从 '+store.value['created'][:10]+' 开始相伴\n\n当前亲密度：'+str(store.value['affinity'])+'\n\n'+STAGES[store.stage][2]
        path,_=QFileDialog.getSaveFileName(self,'保存纪念卡','天依的'+choice+'.png','PNG (*.png)')
        if not path:return
        image=QImage(960,720,QImage.Format_ARGB32);image.fill(QColor('#e9f2f5'))
        painter=QPainter(image);painter.setPen(QColor('#294b61'));painter.setFont(QFont('Microsoft YaHei UI',22,QFont.Bold))
        painter.drawText(48,68,title);painter.setFont(QFont('Microsoft YaHei UI',15))
        painter.drawText(48,110,864,550,Qt.TextWordWrap,body);painter.end()
        message='纪念卡已保存在本机。' if image.save(path,'PNG') else '纪念卡保存失败，请检查位置。'
        self.note.setText(message)
        if self.tabs.currentIndex()==2:QMessageBox.information(self,'导出纪念卡',message)

    def closeEvent(self,event):
        self.refresh_timer.stop()
        self.cancel_analysis()
        self.quiet_started=None
        super().closeEvent(event)
