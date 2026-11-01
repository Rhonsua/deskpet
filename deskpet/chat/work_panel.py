"""Native task view for the official Harness backend; no browser required."""
import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QFileDialog, QCheckBox, QMessageBox,
                               QToolButton, QFrame, QSizePolicy)
from .work_style import WORK_STYLE


def plain(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class WorkInput(QPlainTextEdit):
    def __init__(self, send):
        super().__init__()
        self.send = send
        self.composing = False

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not event.modifiers() and not self.composing):
            self.send()
            event.accept()
        else:
            super().keyPressEvent(event)


class WorkPanel(QWidget):
    def __init__(self, config_provider, parent=None):
        super().__init__(parent)
        from .work_client import WorkClient
        self.client = WorkClient(self)
        self.config_provider = config_provider
        self.approval_id = None
        self.active_approval = None
        self.approval_queue = []
        self.approval_seen = set()
        self.terminal_state = None
        self.tool_calls = {}
        self.tool_arguments = {}
        self.last_event_summary = None
        self.message_seen = set()
        self.last_assistant_text = ''
        self.pending_task = None
        self.pending_folder = None
        self.setObjectName('workPanel')
        self.setStyleSheet(WORK_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.setSpacing(8)
        self.folder_row = QWidget()
        row = QHBoxLayout(self.folder_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText('选择任务的工作目录')
        self.choose = QPushButton('选择文件夹')
        self.choose.clicked.connect(self.choose_folder)
        row.addWidget(self.folder, 1)
        row.addWidget(self.choose)
        layout.addWidget(self.folder_row)

        self.options_box = QFrame()
        self.options_box.setObjectName('workOptions')
        options = QVBoxLayout(self.options_box)
        note = QLabel('首次工作会自动从官方源下载工作环境和 Node.js，准备完成后继续任务，可随时停止。\n工作目录并非文件访问隔离；切换或隐藏页面不会结束任务。')
        note.setWordWrap(True)
        options.addWidget(note)
        self.continue_session = QCheckBox('继续上一工作会话（同一目录）')
        options.addWidget(self.continue_session)
        self.auto_approve = QCheckBox('总是允许普通操作（高风险仍需确认）')
        self.auto_approve.toggled.connect(self.confirm_auto_approve)
        options.addWidget(self.auto_approve)
        self.permission_note = QLabel('普通审批模式；按后端要求确认操作。')
        self.permission_note.setWordWrap(True)
        options.addWidget(self.permission_note)
        self.preview_button = QPushButton('预览工作动作')
        self.preview_button.setToolTip('预览 20 秒，再次点击立即停止；不调用 API，不停止正在执行的工作任务。')
        options.addWidget(self.preview_button)
        layout.addWidget(self.options_box)
        self.options_box.hide()
        self.session_folder = None

        from .conversation_view import ConversationView
        self.log = ConversationView()
        self.log.setStyleSheet('QTextBrowser { background: transparent; border: none; padding: 4px; color: #243541; font-size: 13px; }')
        self.log.setMinimumSize(0, 100)
        self.log.setPlaceholderText('在下面输入任务，和天依一起完成工作。')
        self.latest_scroll = QTimer(self)
        self.latest_scroll.setSingleShot(True)
        self.latest_scroll.timeout.connect(self.show_latest_message)
        layout.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.state = QLabel('准备就绪')
        self.state.setObjectName('workState')
        self.state.setWordWrap(True)
        self.state.setTextFormat(Qt.TextFormat.PlainText)
        self.state.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.state, 1)
        self.details_button = QToolButton()
        self.details_button.setObjectName('workDetailsToggle')
        self.details_button.setText('工作详情')
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.RightArrow)
        row.addWidget(self.details_button)
        layout.addLayout(row)
        self.details_box = QFrame()
        self.details_box.setObjectName('workDetails')
        self.details_box.setMaximumHeight(170)
        details = QVBoxLayout(self.details_box)
        details.setContentsMargins(8, 6, 8, 6)
        self.events = QPlainTextEdit()
        self.events.setObjectName('workEvents')
        self.events.setReadOnly(True)
        self.events.setMaximumBlockCount(1500)
        self.events.setMinimumHeight(45)
        details.addWidget(self.events, 1)
        self.details_toggle = QCheckBox('显示完整事件详情')
        details.addWidget(self.details_toggle)
        self.event_details = QPlainTextEdit()
        self.event_details.setReadOnly(True)
        self.event_details.setMaximumBlockCount(1500)
        self.event_details.setMinimumHeight(45)
        self.event_details.hide()
        self.details_toggle.toggled.connect(self.event_details.setVisible)
        details.addWidget(self.event_details)
        layout.addWidget(self.details_box)
        self.details_box.hide()
        self.details_button.toggled.connect(self.toggle_details)
        self.approval_box = QFrame()
        self.approval_box.setObjectName('workApproval')
        approval_layout = QVBoxLayout(self.approval_box)
        approval_layout.setContentsMargins(10, 6, 10, 8)
        approval_layout.addWidget(QLabel('等待你的确认'))
        self.approval_text = QPlainTextEdit()
        self.approval_text.setObjectName('workApprovalText')
        self.approval_text.setReadOnly(True)
        self.approval_text.setFixedHeight(80)
        self.approval_text.hide()
        approval_layout.addWidget(self.approval_text)
        row = QHBoxLayout()
        self.allow = QPushButton('允许本次操作')
        self.deny = QPushButton('拒绝本次操作')
        self.allow.clicked.connect(lambda: self.answer(True))
        self.deny.clicked.connect(lambda: self.answer(False))
        row.addWidget(self.allow)
        row.addWidget(self.deny)
        approval_layout.addLayout(row)
        layout.addWidget(self.approval_box)
        self.approval_box.hide()
        self.allow.hide()
        self.deny.hide()

        self.composer = QFrame()
        self.composer.setObjectName('workComposer')
        compose = QVBoxLayout(self.composer)
        compose.setContentsMargins(12, 10, 10, 9)
        compose.setSpacing(5)
        self.prompt = WorkInput(self.start)
        self.prompt.setObjectName('workPrompt')
        self.prompt.setPlaceholderText('描述要完成的工作，或者继续追问…')
        self.prompt.setFixedHeight(76)
        compose.addWidget(self.prompt)
        row = QHBoxLayout()
        self.options_button = QToolButton()
        self.options_button.setObjectName('workOptionsToggle')
        self.options_button.setText('工作设置')
        self.options_button.setCheckable(True)
        self.options_button.toggled.connect(self.options_box.setVisible)
        row.addWidget(self.options_button)
        self.input_hint = QLabel('Enter 发送 · Shift+Enter 换行')
        self.input_hint.setObjectName('workHint')
        row.addWidget(self.input_hint, 1)
        self.stop_button = QPushButton('停止工作')
        self.stop_button.setObjectName('workStop')
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.start_button = QPushButton('发送 ↑')
        self.start_button.setObjectName('workSend')
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.stop_button)
        row.addWidget(self.start_button)
        compose.addLayout(row)
        layout.addWidget(self.composer)
        self.client.progress.connect(self.on_progress)
        self.client.event.connect(self.on_event)
        self.client.approval.connect(self.request_approval)
        self.client.busy_changed.connect(self.set_busy)
        self.client.completed.connect(lambda text: self.finish('工作完成', text))
        self.client.failed.connect(lambda text: self.finish('工作已结束，可修改输入后重试', text))

    def showEvent(self, event):
        super().showEvent(event)
        # Hidden tabs have not settled their transcript geometry yet. Scroll
        # once after layout, not on a repeating timer that interrupts reading.
        self.latest_scroll.start(0)

    def show_latest_message(self):
        if self.isVisible():
            self.log.moveCursor(QTextCursor.End)
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def toggle_details(self, expanded):
        self.details_box.setVisible(expanded)
        self.details_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.details_button.setText('收起详情' if expanded else '工作详情')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.input_hint.setVisible(self.width() >= 490)

    @property
    def is_running(self):
        return self.client.busy

    def restore_auto_approve(self, enabled):
        self.auto_approve.blockSignals(True)
        self.auto_approve.setChecked(enabled is True)
        self.auto_approve.blockSignals(False)
        self.update_permission_note()

    def update_permission_note(self):
        self.options_button.setText('工作设置 · 自动审批' if self.auto_approve.isChecked() else '工作设置')
        self.permission_note.setText('已开启：普通操作自动审查后执行；高风险或未获授权的操作仍需确认，审查失败不执行。会额外调用 API，操作可涉及项目目录之外。'
                                    if self.auto_approve.isChecked() else '普通审批模式；按后端要求确认操作。')

    def confirm_auto_approve(self, enabled):
        if enabled:
            answer = QMessageBox.warning(self, '开启总是允许普通操作',
                '开启后，本项目的读取、修改文件和运行命令等普通操作，经官方 Harness 自动审查后直接执行。\n\n'
                '高风险或未获授权的操作仍会请求你确认；审查失败不会执行。'
                '自动审查会额外调用你配置的 API，增加耗时与费用，并使用任务上下文和工具参数。\n\n'
                '自动获准的操作可访问项目文件夹以外的位置，模型判断也可能出错。'
                '此设置会按项目记住，可在任务结束后关闭。是否开启？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.restore_auto_approve(False)
                return
        self.update_permission_note()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择工作目录', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def start(self):
        if self.is_running:
            return
        if not getattr(self, 'can_start', lambda: True)():
            self.on_progress('另一个对话正在工作，请等待结束或返回该对话停止任务。')
            return
        try:
            task = self.prompt.toPlainText().strip()
            folder = self.folder.text().strip()
            if not task:
                raise ValueError('请先填写工作任务。')
            if not folder:
                raise ValueError('请先选择工作目录。')
            self.clear_approval()
            self.approval_seen.clear()
            self.tool_calls.clear()
            self.tool_arguments.clear()
            self.terminal_state = None
            self.last_assistant_text = ''
            self.message_seen.clear()
            session_id = None
            if self.continue_session.isChecked():
                session_id = getattr(self.client, 'session_id', None)
                if not self.client.can_resume():
                    session_id = None
                    self.continue_session.setChecked(False)
                    self.events.appendPlainText('上次会话未成功建立，保留页面记录，本次重新启动。')
                elif self.session_folder != folder:
                    raise ValueError('当前目录没有可继续的会话，请取消勾选以开始新任务。')
            self.pending_task = task
            self.pending_folder = folder
            if self.auto_approve.isChecked():
                self.events.appendPlainText('本次已开启自动审批：普通操作经审查后执行，高风险或未获授权的操作仍需确认。')
            self.client.start(self.config_provider(), task, folder, session_id=session_id,
                              auto_approve=self.auto_approve.isChecked())
            if self.client.busy:
                self.log.append_message('user',task)
        except (ValueError, OSError) as error:
            self.on_progress(str(error))

    def set_busy(self, busy):
        self.start_button.setEnabled(not busy)
        self.start_button.setVisible(not busy)
        self.stop_button.setEnabled(busy)
        self.stop_button.setVisible(busy)
        self.choose.setEnabled(not busy)
        self.continue_session.setEnabled(not busy)
        self.auto_approve.setEnabled(not busy)
        self.folder.setReadOnly(busy)
        self.prompt.setReadOnly(busy)
        if busy and not self.terminal_state:
            self.options_button.setChecked(False)
            self.state.setText('工作中…')
        else:
            self.clear_approval()

    def on_progress(self, message):
        if not self.terminal_state and self.approval_id is None:
            self.state.setText('工作中…' if self.is_running else message)
        self.events.appendPlainText(message)

    def on_event(self, event):
        self.event_details.appendPlainText(plain(event))
        if event.get('type') == 'runtime_setup':
            if not self.terminal_state:
                self.state.setText(event.get('text', '正在准备工作环境…'))
                self.events.appendPlainText(event.get('text', ''))
            return
        if event.get('type') == 'session_ready':
            self.session_folder = self.pending_folder or self.folder.text().strip()
            self.continue_session.setChecked(True)
            if (getattr(self, 'clear_sent_prompt', False) and self.pending_task is not None
                    and self.prompt.toPlainText().strip() == self.pending_task):
                self.prompt.clear()
            self.pending_task = None
            return
        detail = event
        while isinstance(detail.get('event'), dict):
            detail = detail['event']
        data = detail.get('data', detail)
        if not isinstance(data, dict):
            data = {}
        kind = str(detail.get('type', ''))
        lowered = kind.lower()
        if kind == 'assistant/message':
            # Official committed text blocks; omit reasoning and tool arguments.
            parts=[]
            for block in data.get('stream',[]):
                if isinstance(block,dict) and block.get('type')=='text-chunks':
                    parts.extend(x for x in block.get('texts',[]) if isinstance(x,str))
            text=''.join(parts)
            key=(event.get('sessionId',''),detail.get('seq'))
            if text and (key[1] is None or key not in self.message_seen):
                self.message_seen.add(key)
                self.log.append_message('assistant',text)
                self.last_assistant_text=text
            return
        if any(part in lowered for part in ('delta', 'token', 'chunk')):
            return
        tool = data.get('name', data.get('toolName', data.get('tool_name', '')))
        path = data.get('path', data.get('filePath', ''))
        suffix = ''
        if kind == 'tool/call':
            arguments = data.get('arguments', {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            path = arguments.get('path', arguments.get('file_path', path))
            key = (event.get('sessionId', ''), data.get('callId'))
            self.tool_calls[key] = (tool, path)
            self.tool_arguments[key] = (tool, arguments)
            if self.active_approval:
                self.refresh_approval()
            label = '准备读取文件' if tool in ('read', 'read_file') else ('准备写入文件' if tool in ('write', 'edit', 'patch', 'write_file', 'edit_file') else '调用工具')
        elif kind == 'tool/result':
            message = data.get('message', {})
            meta = data.get('meta', {}) or {}
            key = (event.get('sessionId', ''), message.get('toolCallId'))
            tool, original_path = self.tool_calls.pop(key, ('', ''))
            self.tool_arguments.pop(key, None)
            if self.active_approval:
                self.refresh_approval()
            path = meta.get('path', original_path)
            if message.get('isError'):
                label = '工具执行失败'
                suffix = ' '.join(str(block.get('text', '')) for block in message.get('content', []) if isinstance(block, dict))[:240]
            else:
                operation = str(meta.get('operation', ''))
                if operation in ('create', 'write', 'edit', 'patch', 'update') or tool in ('write', 'write_file', 'edit', 'edit_file', 'patch'):
                    label = '文件已写入'
                elif operation == 'read' or tool in ('read', 'read_file'):
                    label = '读取完成'
                else:
                    label = '工具执行完成'
        elif path or any(part in lowered for part in ('file', 'edit', 'write', 'patch')):
            if any(part in lowered for part in ('changed', 'write', 'edit', 'patch', 'created', 'deleted')):
                label = '文件变化'
            else:
                label = '读取文件' if 'read' in lowered else '文件操作'
        elif 'status' in lowered:
            label = '状态更新'
            suffix = {'running': '进行中', 'idle': '空闲', 'completed': '已完成', 'failed': '失败'}.get(str(data.get('status', '')), str(data.get('status', '')))
        else:
            label = {'started': '任务开始', 'completed': '任务完成', 'cancelled': '任务停止', 'failed': '任务失败'}.get(kind)
            if not label:
                return
        summary = ' · '.join(str(x) for x in (label, tool, path, suffix) if x)
        if summary != self.last_event_summary:
            self.events.appendPlainText(summary)
            self.last_event_summary = summary

    def request_approval(self, request):
        if not self.is_running or self.terminal_state:
            return
        request_id = request.get('id')
        if request_id is None:
            self.on_progress('收到缺少标识的审批请求，未执行操作。')
            return
        if request_id in self.approval_seen:
            return
        self.approval_seen.add(request_id)
        self.approval_queue.append(request)
        if self.approval_id is None:
            self.show_next_approval()

    def show_next_approval(self):
        if not self.approval_queue:
            return
        request = self.approval_queue.pop(0)
        self.approval_id = request['id']
        self.active_approval = request
        self.refresh_approval()
        self.details_button.setChecked(False)
        self.log.setMinimumHeight(40)
        self.approval_box.show()
        self.approval_text.show()
        self.allow.show()
        self.deny.show()

    def refresh_approval(self):
        # Official approval/request carries a callId, not the command arguments.
        # Bind the matching session's tool/call before enabling approval, even
        # when the request and notification arrive in the opposite order.
        request = self.active_approval
        if request is None:
            return
        display = dict(request)
        key = (request.get('sessionId', ''), request.get('callId'))
        tool, arguments = self.tool_arguments.get(key, ('', None))
        known = isinstance(request.get('arguments'), dict)
        if arguments is not None and tool == request.get('toolName'):
            display['arguments'] = arguments
            known = True
        self.approval_text.setPlainText(plain(display))
        self.allow.setEnabled(known)
        self.state.setText('等待你审批下方操作；允许或拒绝均只针对本次请求。' if known else
                           '正在等待该操作的完整参数；暂不能允许，仍可拒绝或停止任务。')

    def clear_approval(self):
        self.approval_queue.clear()
        self.hide_approval()

    def hide_approval(self):
        self.approval_id = None
        self.active_approval = None
        self.approval_text.clear()
        self.approval_text.hide()
        self.approval_box.hide()
        self.log.setMinimumHeight(100)
        self.allow.hide()
        self.deny.hide()

    def answer(self, approved):
        if self.approval_id is None or not self.is_running:
            return
        if approved and not self.allow.isEnabled():
            return
        request_id = self.approval_id
        self.hide_approval()
        self.client.approve(request_id, approved)
        self.state.setText('已允许本次操作，工作继续中…' if approved else '已拒绝本次操作，等待任务更新…')
        if self.is_running:
            self.show_next_approval()

    def finish(self, state, text):
        self.terminal_state = state
        self.clear_approval()
        self.state.setText(state)
        if text and text != self.last_assistant_text:
            self.log.append_message('assistant',text)
        if not self.client.can_resume():
            self.continue_session.setChecked(False)
        self.set_busy(self.is_running)

    def stop(self):
        self.terminal_state = '正在停止工作…'
        self.clear_approval()
        self.client.cancel()
        self.state.setText(self.terminal_state)

    def shutdown(self):
        self.clear_approval()
        self.client.shutdown()
