"""Project sidebar and persistent native conversations, independent of the backend."""
import json
import os
import uuid
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QSaveFile, QIODevice, QSignalBlocker
from PySide6.QtGui import QColor, QBrush, QPalette
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget,
    QLabel, QFileDialog, QFrame, QSplitter, QTreeWidget, QTreeWidgetItem, QLineEdit,
    QToolButton, QSizePolicy, QStyle)
from .work_panel import WorkPanel
from .work_style import WORK_STYLE


class Workspaces(QWidget):
    def __init__(self, config_provider, data_dir, parent=None):
        super().__init__(parent)
        self.setObjectName('workspaces')
        self.setStyleSheet(WORK_STYLE)
        self.config_provider = config_provider
        self.path = Path(data_dir) / 'work-projects.json'
        self.background_path = None
        self.pages = {}
        self.project_records = {}
        self.project_items = {}
        self.conversation_items = {}
        self.last_saved = None
        self.storage_ok = True
        self.legacy_backup = None
        self.selected_id = None
        self.selected_project_key = None
        self.sidebar_requested = True
        self.sidebar_width = 220
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName('workspaceSplitter')
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(7)
        layout.addWidget(self.splitter)

        self.sidebar = QFrame()
        self.sidebar.setObjectName('workspaceSidebar')
        self.sidebar.setMinimumWidth(160)
        self.sidebar.setMaximumWidth(330)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(10, 12, 10, 12)
        heading = QLabel('项目与对话')
        heading.setObjectName('sidebarTitle')
        side.addWidget(heading)
        self.new_button = QPushButton('＋ 新对话')
        self.new_button.clicked.connect(lambda: self.new_conversation())
        side.addWidget(self.new_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索项目或对话')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_tree)
        side.addWidget(self.search)
        self.projects = QTreeWidget()
        self.projects.setObjectName('workspaceTree')
        self.projects.setHeaderHidden(True)
        self.projects.setIndentation(14)
        self.projects.setExpandsOnDoubleClick(False)
        self.projects.setTextElideMode(Qt.ElideRight)
        self.projects.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.projects.viewport().setAutoFillBackground(False)
        palette = self.projects.palette()
        palette.setColor(QPalette.Highlight, QColor(255, 255, 255, 0))
        self.projects.setPalette(palette)
        self.projects.currentItemChanged.connect(self.select_item)
        side.addWidget(self.projects, 1)
        self.add_button = QPushButton('＋ 添加项目文件夹')
        self.add_button.clicked.connect(self.choose_project)
        side.addWidget(self.add_button)
        self.splitter.addWidget(self.sidebar)

        self.main = QFrame()
        self.main.setObjectName('workspaceMain')
        self.main.setMinimumWidth(330)
        body = QVBoxLayout(self.main)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(12, 12, 12, 4)
        self.sidebar_button = QToolButton()
        self.sidebar_button.setText('项目')
        self.sidebar_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.sidebar_button.setArrowType(Qt.LeftArrow)
        self.sidebar_button.setToolTip('展开或收起项目列表')
        self.sidebar_button.clicked.connect(self.toggle_sidebar)
        header.addWidget(self.sidebar_button)
        names = QVBoxLayout()
        names.setSpacing(3)
        self.title = QLabel('和天依一起工作')
        self.title.setObjectName('workspaceTitle')
        self.title.setTextFormat(Qt.PlainText)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.project_path = QLabel('选择一个项目，开始新的对话')
        self.project_path.setObjectName('workspacePath')
        self.project_path.setTextFormat(Qt.PlainText)
        self.project_path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        names.addWidget(self.title)
        names.addWidget(self.project_path)
        header.addLayout(names, 1)
        self.add_compact = QToolButton()
        self.add_compact.setText('＋')
        self.add_compact.setToolTip('添加项目文件夹')
        self.add_compact.clicked.connect(self.choose_project)
        header.addWidget(self.add_compact)
        self.new_compact = QToolButton()
        self.new_compact.setText('＋ 新对话')
        self.new_compact.clicked.connect(lambda: self.new_conversation())
        self.new_compact.hide()
        header.addWidget(self.new_compact)
        self.preview_button = QPushButton('预览工作动作')
        header.addWidget(self.preview_button)
        body.addLayout(header)
        self.notice = QLabel()
        self.notice.setObjectName('workspaceNotice')
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.PlainText)
        self.notice.setContentsMargins(14, 0, 14, 0)
        self.notice.hide()
        body.addWidget(self.notice)
        self.active_button = QPushButton('返回正在工作的对话')
        self.active_button.clicked.connect(self.show_running)
        self.active_button.hide()
        body.addWidget(self.active_button)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(self.stack, 1)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        self.welcome = QLabel('从一个项目开始')
        self.welcome.setObjectName('workspaceTitle')
        self.welcome.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.welcome)
        self.instruction = QLabel('添加工作文件夹，天依会在这里和你讨论任务。\n历史对话和草稿会按项目保留。')
        self.instruction.setObjectName('workHint')
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setWordWrap(True)
        empty_layout.addWidget(self.instruction)
        start = QPushButton('选择项目文件夹')
        start.clicked.connect(self.choose_project)
        empty_layout.addWidget(start, 0, Qt.AlignHCenter)
        empty_layout.addStretch()
        self.stack.addWidget(self.empty)
        self.splitter.addWidget(self.main)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self.remember_splitter)
        self.restore()
        self.splitter.setSizes([self.sidebar_width, 680])
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.save)
        self.timer.start(1000)

    @property
    def is_running(self):
        return any(p.is_running for p in self.pages.values())

    @property
    def terminal_state(self):
        return next((p.terminal_state for p in self.pages.values() if p.is_running), None)

    @property
    def approval_id(self):
        return next((p.approval_id for p in self.pages.values()
                     if p.is_running and p.approval_id is not None), None)

    def set_background(self, path):
        self.background_path = path
        for page in self.pages.values():
            page.log.set_background(path)

    def choose_project(self):
        folder = QFileDialog.getExistingDirectory(self, '选择项目文件夹')
        if folder:
            return self.add_project(folder)

    def ensure_project(self, folder):
        folder = str(Path(folder).resolve())
        key = os.path.normcase(folder)
        if key not in self.project_records:
            self.project_records[key] = {'folder': folder, 'selected': None}
            item = QTreeWidgetItem([Path(folder).name or folder])
            item.setData(0, Qt.UserRole, key)
            item.setData(0, Qt.UserRole + 1, 'project')
            item.setToolTip(0, folder)
            item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
            font = item.font(0); font.setBold(True); item.setFont(0, font)
            self.projects.addTopLevelItem(item)
            item.setExpanded(True)
            self.project_items[key] = item
        return key

    def add_project(self, folder, saved=None):
        key = self.ensure_project(folder)
        previous = self.project_records[key]['selected']
        if previous in self.pages and saved is None:
            self.select_conversation(previous)
            return self.pages[previous]
        return self.new_conversation(key, saved)

    def new_conversation(self, project_key=None, saved=None):
        current = self.pages.get(self.selected_id)
        project_key = project_key or (current.project_key if current else self.selected_project_key)
        if project_key not in self.project_records:
            return self.choose_project()
        if saved is None:
            self.search.clear()
            for identifier, page in self.pages.items():
                if page.project_key == project_key and self.is_unused(page):
                    self.select_conversation(identifier)
                    page.prompt.setFocus()
                    return page
        record = self.project_records[project_key]
        folder = record['folder']
        saved = saved or {}
        if not saved:
            self.search.clear()
        identifier = saved.get('id') or uuid.uuid4().hex
        if identifier in self.pages:
            raise ValueError('duplicate conversation')
        p = WorkPanel(self.config_provider, self)
        p.project_key = project_key
        p.conversation_id = identifier
        p.conversation_title = str(saved.get('title') or '新对话')
        p.conversation_used = bool(saved.get('used') or saved.get('session_id') or saved.get('running'))
        p.log.set_background(self.background_path)
        p.clear_sent_prompt = True
        p.folder.setText(folder)
        p.folder.setEnabled(False)
        p.folder_row.hide()
        p.choose.hide()
        p.preview_button.hide()
        # The sidebar creates separate conversations. Continuing here never
        # resets or replaces a sibling conversation's backend session.
        p.continue_session.hide()
        p.can_start = lambda: not any(other.is_running for other in self.pages.values() if other is not p)
        self.pages[identifier] = p
        self.stack.addWidget(p)
        if saved:
            p.restore_auto_approve(saved.get('auto_approve') is True)
            p.client.session_id = saved.get('session_id')
            p.session_folder = folder
            p.prompt.setPlainText(saved.get('draft', ''))
            p.log.setPlainText(saved.get('log', ''))
            if isinstance(saved.get('messages'), list) and saved['messages']:
                p.log.set_messages([m for m in saved['messages']
                    if isinstance(m, dict) and isinstance(m.get('content'), str)])
            p.events.setPlainText(saved.get('events', ''))
            p.state.setText('上次任务已中断，可继续会话；不会自动重新执行。'
                            if saved.get('running') else saved.get('state', '准备就绪'))
            if p.conversation_title == '新对话':
                first = next((m['content'] for m in p.log.messages if m.get('role') == 'user'), '')
                p.conversation_title = self.task_title(first) if first else (
                    '历史对话' if p.log.toPlainText().strip() else '新对话')
        resumable = p.client.can_resume()
        p.continue_session.setChecked(resumable and saved.get('continue_session', True))
        if saved and (p.client.session_id or saved.get('running')) and not resumable:
            p.client.session_id = None
            p.state.setText('上次会话未成功建立，输入和历史已保留；可直接开始工作重试。')
        item = QTreeWidgetItem([p.conversation_title])
        item.setData(0, Qt.UserRole, identifier)
        item.setData(0, Qt.UserRole + 1, 'conversation')
        self.project_items[project_key].addChild(item)
        self.conversation_items[identifier] = item
        p.client.busy_changed.connect(self.refresh_status)
        p.client.approval.connect(lambda _: self.refresh_status())
        p.client.completed.connect(lambda _: self.on_terminal())
        p.client.failed.connect(lambda _: self.on_terminal())
        p.allow.clicked.connect(lambda: self.refresh_status())
        p.deny.clicked.connect(lambda: self.refresh_status())
        self.select_conversation(identifier)
        self.filter_tree(self.search.text())
        return p

    @staticmethod
    def is_unused(page):
        # Keep unsent drafts and every task that reached the backend, including
        # failed/interrupted tasks. Only untouched placeholders are disposable.
        return not (page.conversation_used or page.is_running or page.pending_task
                    or page.client.session_id or page.approval_id is not None
                    or page.prompt.toPlainText().strip() or page.log.toPlainText().strip()
                    or page.events.toPlainText().strip())

    @staticmethod
    def unused_record(saved):
        if saved.get('used') or saved.get('session_id') or saved.get('running'):
            return False
        if any(saved.get(name, '').strip() for name in ('draft', 'log', 'events')):
            return False
        messages = saved.get('messages')
        return not (isinstance(messages, list) and any(isinstance(message, dict)
            and isinstance(message.get('content'), str) and message['content'].strip()
            for message in messages))

    @staticmethod
    def task_title(task):
        return ' '.join(task.split())[:48] or '新对话'

    def select_item(self, item, previous=None):
        if item is None:
            return
        identifier = item.data(0, Qt.UserRole)
        if item.data(0, Qt.UserRole + 1) == 'project':
            return self.select_project(identifier)
        self.select_conversation(identifier)

    def select_project(self, key):
        if key not in self.project_records:
            return
        identifier = self.project_records[key]['selected']
        if identifier in self.pages:
            return self.select_conversation(identifier)
        self.selected_id = None
        self.selected_project_key = key
        self.stack.setCurrentWidget(self.empty)
        with QSignalBlocker(self.projects):
            self.projects.setCurrentItem(self.project_items[key])
        self.refresh_status()

    def select_conversation(self, identifier):
        if identifier not in self.pages:
            return
        self.selected_id = identifier
        p = self.pages[identifier]
        self.selected_project_key = p.project_key
        self.project_records[p.project_key]['selected'] = identifier
        self.stack.setCurrentWidget(p)
        with QSignalBlocker(self.projects):
            self.projects.setCurrentItem(self.conversation_items[identifier])
            self.project_items[p.project_key].setExpanded(True)
        self.refresh_status()

    def show_running(self):
        identifier = next((key for key, p in self.pages.items() if p.is_running), None)
        if identifier:
            self.select_conversation(identifier)

    def refresh_status(self, *unused):
        for identifier, page in self.pages.items():
            if page.is_running or page.pending_task or page.client.session_id:
                page.conversation_used = True
            if page.conversation_title == '新对话' and page.pending_task and page.is_running:
                page.conversation_title = self.task_title(page.pending_task)
            item = self.conversation_items[identifier]
            suffix = ' · 待确认' if page.approval_id is not None else (' · 进行中' if page.is_running else '')
            item.setText(0, page.conversation_title + suffix)
            item.setToolTip(0, page.conversation_title + suffix)
            item.setForeground(0, QBrush(QColor('#946323' if page.approval_id is not None else '#344C5C')))
        current = self.pages.get(self.selected_id)
        if current:
            folder = current.folder.text()
            self.title.setText(current.conversation_title)
            self.title.setToolTip(current.conversation_title)
            self.project_path.setText((Path(folder).name or folder) + '  ·  ' + folder)
            self.project_path.setToolTip(folder)
        else:
            record = self.project_records.get(self.selected_project_key)
            folder = record['folder'] if record else ''
            self.title.setText('和天依一起工作')
            self.title.setToolTip('')
            self.project_path.setText(((Path(folder).name or folder) + '  ·  ' + folder)
                                      if folder else '选择一个项目，开始新的对话')
            self.project_path.setToolTip(folder)
            self.welcome.setText('开始新的对话' if record else '从一个项目开始')
            self.instruction.setText('点击“＋ 新对话”，在当前项目里开始工作。\n历史对话和草稿会按项目保留。'
                                     if record else '添加工作文件夹，天依会在这里和你讨论任务。\n历史对话和草稿会按项目保留。')
        self.active_button.setVisible(any(p.is_running and p is not current for p in self.pages.values()))

    def on_terminal(self):
        self.refresh_status()
        self.save()

    def filter_tree(self, text):
        needle = text.casefold().strip()
        for key, item in self.project_items.items():
            matches_project = needle in self.project_records[key]['folder'].casefold()
            any_match = matches_project
            for index in range(item.childCount()):
                child = item.child(index)
                page = self.pages[child.data(0, Qt.UserRole)]
                matches = matches_project or needle in page.conversation_title.casefold()
                child.setHidden(not matches)
                any_match |= matches
            item.setHidden(not any_match)

    def toggle_sidebar(self):
        self.sidebar_requested = self.sidebar.isHidden()
        self.set_sidebar_visible(self.sidebar_requested)
        if self.sidebar_requested:
            self.splitter.setSizes([self.sidebar_width, max(330, self.width() - self.sidebar_width - 7)])
        self.save()

    def set_sidebar_visible(self, visible):
        self.sidebar.setVisible(visible)
        self.sidebar_button.setArrowType(Qt.LeftArrow if visible else Qt.RightArrow)
        self.new_compact.setVisible(not visible)

    def remember_splitter(self, *unused):
        sizes = self.splitter.sizes()
        if sizes and sizes[0] >= 160:
            self.sidebar_width = sizes[0]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Small screens keep the composer usable; the list can still be opened
        # with the persistent header button, and reappears on wider windows.
        self.set_sidebar_visible(self.sidebar_requested and self.width() >= 700)
        self.preview_button.setVisible(self.width() >= 800)
        self.project_path.setMaximumHeight(20)

    def restore(self):
        if not self.path.exists():
            return
        try:
            raw = self.path.read_bytes()
            data = json.loads(raw)
            version = data.get('version')
            if version not in (1, 2) or not isinstance(data.get('projects'), list):
                raise ValueError('unsupported project record')
            normalized = []
            seen_ids, seen_folders = set(), set()
            for record in data['projects']:
                if not isinstance(record, dict) or not isinstance(record.get('folder'), str) or not record['folder']:
                    raise ValueError('invalid project')
                key = os.path.normcase(str(Path(record['folder']).resolve()))
                if key in seen_folders:
                    raise ValueError('duplicate project')
                seen_folders.add(key)
                conversations = [record] if version == 1 else record.get('conversations')
                if not isinstance(conversations, list):
                    raise ValueError('invalid conversations')
                for saved in conversations:
                    if not isinstance(saved, dict):
                        raise ValueError('invalid conversation')
                    if version == 2:
                        identifier = saved.get('id')
                        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
                            raise ValueError('invalid conversation id')
                        seen_ids.add(identifier)
                    for name in ('draft', 'log', 'events', 'state', 'title'):
                        if name in saved and not isinstance(saved[name], str):
                            raise ValueError('invalid conversation text')
                normalized.append((key, record, conversations))
            for key, record, conversations in normalized:
                self.ensure_project(record['folder'])
                for saved in conversations:
                    if not self.unused_record(saved):
                        self.new_conversation(key, saved)
                selected = record.get('selected')
                if selected in self.pages and self.pages[selected].project_key == key:
                    self.project_records[key]['selected'] = selected
            if version == 1:
                self.legacy_backup = raw
                selected_project = data.get('selected')
                selected = self.project_records.get(selected_project, {}).get('selected')
            else:
                selected = data.get('selected')
            if selected in self.pages:
                self.select_conversation(selected)
            else:
                project_key = data.get('selected') if version == 1 else data.get('selected_project')
                if project_key not in self.project_records:
                    project_key = next((key for key, record, _ in normalized
                                        if record.get('selected') == selected), None)
                if project_key in self.project_records:
                    self.select_project(project_key)
                elif self.project_records and not self.pages:
                    self.select_project(next(iter(self.project_records)))
            self.filter_tree(self.search.text())
            self.sidebar_requested = data.get('sidebar_visible', True) is not False
            width = data.get('sidebar_width', 220)
            self.sidebar_width = max(160, min(330, width)) if isinstance(width, int) else 220
        except (OSError, ValueError, KeyError, TypeError):
            self.storage_ok = False
            self.notice.setText('项目记录无法读取，已保留原文件；请先修复记录文件。')
            self.notice.show()

    @staticmethod
    def write_record(path, raw):
        f = QSaveFile(str(path))
        if not f.open(QIODevice.WriteOnly):
            raise OSError(f.errorString())
        if f.write(raw) != len(raw):
            f.cancelWriting()
            raise OSError('write failed')
        if not f.commit():
            raise OSError(f.errorString())

    def save(self):
        if not self.storage_ok:
            return
        projects = []
        persisted_ids = set()
        for key, record in self.project_records.items():
            conversations = []
            for identifier, p in self.pages.items():
                if p.project_key != key or self.is_unused(p):
                    continue
                persisted_ids.add(identifier)
                conversations.append({'id': identifier, 'title': p.conversation_title,
                    'used': p.conversation_used,
                    'session_id': p.client.session_id, 'draft': p.prompt.toPlainText(),
                    'continue_session': p.continue_session.isChecked(),
                    'auto_approve': p.auto_approve.isChecked(), 'log': p.log.toPlainText(),
                    'messages': p.log.messages, 'events': p.events.toPlainText(),
                    'state': p.state.text(), 'running': p.is_running})
            selected = record['selected']
            if selected not in {conversation['id'] for conversation in conversations}:
                selected = conversations[-1]['id'] if conversations else None
            projects.append(dict(record, selected=selected, conversations=conversations))
        selected = self.selected_id if self.selected_id in persisted_ids else next(
            (record['selected'] for record in projects
             if os.path.normcase(record['folder']) == self.selected_project_key), None)
        data = {'version': 2, 'selected': selected, 'selected_project': self.selected_project_key,
                'sidebar_visible': self.sidebar_requested, 'sidebar_width': self.sidebar_width,
                'projects': projects}
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        if raw == self.last_saved:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.legacy_backup is not None:
                # Keep one exact pre-migration backup, never erase old history.
                self.write_record(self.path.with_suffix('.v1.backup.json'), self.legacy_backup)
                self.legacy_backup = None
            self.write_record(self.path, raw)
            self.last_saved = raw
            self.notice.hide()
        except OSError:
            self.notice.setText('项目记录保存失败，请检查磁盘空间；当前页面仍保留。')
            self.notice.show()

    def discard_unused(self):
        removed = [identifier for identifier, page in self.pages.items() if self.is_unused(page)]
        if not removed:
            return
        with QSignalBlocker(self.projects):
            for identifier in removed:
                page = self.pages.pop(identifier)
                item = self.conversation_items.pop(identifier)
                item.parent().removeChild(item)
                self.stack.removeWidget(page)
                page.shutdown()
                page.deleteLater()
        for key, record in self.project_records.items():
            if record['selected'] not in self.pages:
                record['selected'] = next((identifier for identifier, page in reversed(self.pages.items())
                                           if page.project_key == key), None)
        if self.selected_id in removed:
            self.select_project(self.selected_project_key)
        self.filter_tree(self.search.text())

    def shutdown(self):
        self.timer.stop()
        self.discard_unused()
        self.save()
        self.storage_ok = False
        for page in self.pages.values():
            page.shutdown()
