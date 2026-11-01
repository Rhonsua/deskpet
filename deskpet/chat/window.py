"""On-demand text chat, provider settings and per-character persona/notes."""
import html
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QLabel, QLineEdit, QPlainTextEdit, QTextBrowser, QPushButton,
                               QCheckBox, QFormLayout, QMessageBox)

from deskpet.ui.theme import apply_light_palette, CONTROL_STYLE
from .config import ConfigFile, ProviderConfig
from .store import ChatStore
from .prompts import build_messages, parse_reply
from .personality import load_personality
from .scope import request_refusal, response_refusal
from .chat_surface import ChatSurface, GLASS_STYLE


STYLE = '''
QWidget { background: #FFFFFF; color: #000000; font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; font-size: 12px; }
QLineEdit, QPlainTextEdit, QTextBrowser { background: #FFFFFF; color: #000000;
    border: 1px solid #AFC8D3; border-radius: 5px; padding: 7px;
    selection-background-color: #DCECF2; selection-color: #000000; }
QPushButton { background: #FFFFFF; color: #000000; border: 1px solid #91AAB7;
    border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #EDF6F9; }
QPushButton:disabled { color: #777777; border-color: #D9E4EA; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 9px 16px; }
QTabBar::tab:selected { border-bottom: 2px solid #4D8C9F; }
QLabel { background: transparent; }
''' + CONTROL_STYLE


class MessageInput(QPlainTextEdit):
    def __init__(self, send):
        super().__init__()
        self.send = send

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            self.send()
        else:
            super().keyPressEvent(event)


def bounded(editor, limit):
    def enforce():
        value = editor.toPlainText()
        if len(value) > limit:
            editor.setPlainText(value[:limit])
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            editor.setTextCursor(cursor)
    editor.textChanged.connect(enforce)


class ChatWindow(ChatSurface):
    def __init__(self, pet):
        # Keep an ordinary independent window: a topmost pet owner can also
        # keep its owned tool windows above other applications on Windows.
        super().__init__(None, Qt.WindowType.Window)
        self.pet = pet
        root = pet.panel.data_dir / 'chat'
        root.mkdir(parents=True, exist_ok=True)
        self.config_file = ConfigFile(root / 'config.json')
        self.config, warning = self.config_file.load()
        self.store = ChatStore(root / 'chat.db')
        self.client = None
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.flush_partial)
        self.partial_text = ''
        self._reply_start = None
        self._reply_text = ''
        self.saved_profile = None
        self.character = None
        self.name = ''
        self.personality = None
        self.personality_warning = ''
        self.pending = None
        self.pending_action_context = None
        self.pending_actions = ()
        self.pending_music_snapshot = None
        self.music_choice = None
        self.drafts = {}
        self.profile_drafts = {}
        self.profile_draft_names = {}
        self.testing = False
        self.closed = False
        self.resize(430, 565)
        self.setMinimumSize(390, 470)
        apply_light_palette(self)
        outer = QVBoxLayout(self)
        from .balance import BalanceBadge
        self.balance_badge = BalanceBadge(lambda:self.config,self)
        balance_row = QHBoxLayout()
        background_button = QPushButton('更换背景')
        background_button.clicked.connect(self.choose_background)
        self.background_position_button = QPushButton('调整位置')
        self.background_position_button.setToolTip('拖动预览或使用滑块，调整整窗背景的位置和缩放')
        self.background_position_button.clicked.connect(self.adjust_background_position)
        reset_background = QPushButton('默认背景')
        reset_background.clicked.connect(self.clear_background)
        balance_row.addWidget(background_button)
        balance_row.addWidget(self.background_position_button)
        balance_row.addWidget(reset_background)
        balance_row.addStretch()
        balance_row.addWidget(self.balance_badge)
        outer.addLayout(balance_row)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(
            lambda index: QTimer.singleShot(0, self.flush_partial) if index == 0 else None)
        outer.addWidget(self.tabs)
        chat = QWidget()
        layout = QVBoxLayout(chat)
        layout.setContentsMargins(0, 8, 0, 0)
        self.proactive_toggle = QCheckBox('空闲时由 AI 主动聊天（会调用 API）')
        self.proactive_toggle.setToolTip('以当前人设自由选题，也可接续对话；记忆和历史仅作参考。空闲至少 45 秒，调用间隔至少 5 分钟。请求失败时不使用固定台词替代。')
        self.proactive_toggle.setChecked(self.pet.panel.settings.value('companion/proactive_chat', False, type=bool))
        self.actions_toggle = QCheckBox('空闲时自主小动作')
        self.actions_toggle.setChecked(self.pet.panel.settings.value('companion/autonomous_actions', False, type=bool))
        self.proactive_toggle.toggled.connect(lambda enabled: self.set_companion_option('chat', enabled))
        self.actions_toggle.toggled.connect(lambda enabled: self.set_companion_option('actions', enabled))
        layout.addWidget(self.proactive_toggle)
        layout.addWidget(self.actions_toggle)
        self.restore_button = QPushButton('恢复平时状态')
        self.restore_button.setToolTip('退出休息、手机或动作预览，恢复普通姿势；音乐和工作任务继续。')
        self.restore_button.clicked.connect(self.restore_normal)
        layout.addWidget(self.restore_button)
        from .conversation_view import ConversationView
        self.history_view = ConversationView()
        self.background_path = root / 'background.png'
        from deskpet.ui.background_controls import PageBackgrounds
        self.backgrounds = PageBackgrounds(self, self.pet.panel.settings, self.background_path,
            'chat/background', self.background_position_button,
            notify=lambda text: self.status.setText(text))
        self.backgrounds.activate('companion', '陪伴模式')
        self.history_view.setOpenLinks(False)
        self.history_view.setOpenExternalLinks(False)
        layout.addWidget(self.history_view, 1)
        self.input = MessageInput(self.send_message)
        bounded(self.input, 4000)
        self.input.setMaximumHeight(90)
        self.input.setPlaceholderText('说点什么吧…  Enter 发送，Shift+Enter 换行')
        layout.addWidget(self.input)
        row = QHBoxLayout()
        self.clear_button = QPushButton('清空聊天')
        self.clear_button.clicked.connect(self.clear_history)
        row.addWidget(self.clear_button)
        row.addStretch()
        self.stop_button = QPushButton('停止')
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)
        self.send_button = QPushButton('发送')
        self.send_button.clicked.connect(self.send_message)
        row.addWidget(self.send_button)
        layout.addLayout(row)
        self.tabs.addTab(chat, '陪伴模式')

        provider = QWidget()
        layout = QVBoxLayout(provider)
        notice = QLabel('消息、人设、记忆、歌单名和少量桌宠状态将发送到你填写的模型服务。\n'
                        '测试连接也会发送一次简短请求，可能产生服务商费用。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.url_input = QLineEdit(self.config.base_url)
        self.url_input.setPlaceholderText('https://你的服务地址/v1')
        self.url_input.setMaxLength(2048)
        self.model_input = QLineEdit(self.config.model)
        self.model_input.setPlaceholderText('填写服务商提供的模型 ID')
        self.model_input.setMaxLength(200)
        self.key_input = QLineEdit(self.config.api_key)
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setMaxLength(4096)
        self.key_input.setPlaceholderText('API Key；无需鉴权的本地服务可留空')
        form.addRow('接口地址', self.url_input)
        form.addRow('模型名称', self.model_input)
        form.addRow('API Key', self.key_input)
        layout.addLayout(form)
        self.remember_key = QCheckBox('在本机记住 Key（Windows 加密保护）')
        self.remember_key.setChecked(self.config.remember_key)
        layout.addWidget(self.remember_key)
        self.stream_toggle = QCheckBox('流式显示回复（服务不支持时可关闭）')
        self.stream_toggle.setChecked(self.config.stream)
        layout.addWidget(self.stream_toggle)
        row = QHBoxLayout()
        self.save_button = QPushButton('保存配置')
        self.save_button.clicked.connect(self.save_config)
        row.addWidget(self.save_button)
        self.test_button = QPushButton('测试连接')
        self.test_button.clicked.connect(self.test_connection)
        row.addWidget(self.test_button)
        layout.addLayout(row)
        note = QLabel('支持 Chat Completions 兼容接口。可填写 /v1 基址或完整的 '
                      '/chat/completions 地址；无路径时默认补 /v1。\n'
                      '不记住 Key 时仅在本次程序运行中使用。')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self.tabs.addTab(provider, 'API 设置')

        profile = QWidget()
        layout = QVBoxLayout(profile)
        self.personality_label = QLabel()
        self.personality_label.setTextFormat(Qt.TextFormat.PlainText)
        self.personality_label.setWordWrap(True)
        layout.addWidget(self.personality_label)
        layout.addWidget(QLabel('角色人设 · Prompt（最多 8000 字符）'))
        self.persona_input = QPlainTextEdit()
        bounded(self.persona_input, 8000)
        layout.addWidget(self.persona_input, 3)
        layout.addWidget(QLabel('记住的事情（手动编辑，最多 6000 字符）'))
        self.memory_input = QPlainTextEdit()
        self.memory_input.setPlaceholderText('例如：称呼我为小林；我喜欢安静地听歌。\n只填写你希望发送给模型的信息。')
        bounded(self.memory_input, 6000)
        layout.addWidget(self.memory_input, 2)
        note = QLabel('已有自定义人设会保留。可套用角色默认人设，再自行编辑；Ctrl+Z 撤销套用。\n'
                      '修改在发送、切换角色或关闭窗口时自动保存。清空聊天不会删除这里的记忆。')
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        save = QPushButton('保存人设与记忆')
        save.clicked.connect(self.save_profile)
        row.addWidget(save)
        reset = QPushButton('套用角色默认人设')
        reset.clicked.connect(self.restore_persona)
        row.addWidget(reset)
        layout.addLayout(row)
        self.tabs.addTab(profile, '人设与记忆')
        from .workspaces import Workspaces
        self.work_panel = Workspaces(lambda: self.config, self.pet.panel.data_dir, self)
        self.work_panel.preview_button.clicked.connect(lambda: self.pet.preview_work_animation())
        self.work_index = self.tabs.addTab(self.work_panel, '工作模式')
        self.companion_mode_enabled = True
        self.tabs.currentChanged.connect(self.on_mode_changed)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.status)
        self.setStyleSheet(GLASS_STYLE)
        self.sync_character()
        self.set_busy(False)
        self.status.setText('；'.join(filter(None, (warning, self.personality_warning)))
                            or '填写 API 设置后即可聊天；本地历史不会自动全部上传。')
        if not self.config.model:
            self.tabs.setCurrentIndex(1)
        from .companion_runtime import CompanionRuntime
        self.companion_runtime = CompanionRuntime(self)
        self.companion_runtime.set_enabled(self.companion_mode_enabled)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def set_companion_option(self, option, enabled):
        key = 'proactive_chat' if option == 'chat' else 'autonomous_actions'
        self.pet.panel.settings.setValue('companion/' + key, enabled)
        runtime = getattr(self, 'companion_runtime', None)
        if runtime:
            (runtime.set_chat_enabled if option == 'chat' else runtime.set_actions_enabled)(enabled)

    def cancel_proactive(self):
        runtime = getattr(self, 'companion_runtime', None)
        if runtime:
            runtime.cancel()

    def on_mode_changed(self, index):
        pages = ('companion', 'api', 'persona', 'work')
        if 0 <= index < len(pages):
            self.backgrounds.activate(pages[index], self.tabs.tabText(index))
        if index == self.work_index:
            area = self.screen().availableGeometry()
            self.setMinimumSize(min(590, area.width() - 40), min(520, area.height() - 60))
            if not getattr(self, '_work_layout_opened', False):
                self.resize(min(max(self.width(), 960), area.width() - 40),
                            min(max(self.height(), 760), area.height() - 60))
                self._work_layout_opened = True
        else:
            self.setMinimumSize(390, 470)
        self.status.setVisible(index != self.work_index)
        if index in (0, self.work_index):
            self.companion_mode_enabled = index == 0
            runtime = getattr(self, 'companion_runtime', None)
            if runtime:
                runtime.set_enabled(self.companion_mode_enabled)

    def sync_character(self):
        key = self.pet.variant if self.pet.character_pack else 'builtin:luotianyi'
        if key == self.character:
            if self.name != self.pet.character_name:
                self.name = self.pet.character_name
                self.setWindowTitle(self.name + ' · 聊天')
                self.render_history()
            return
        if self.character is not None:
            self.cancel_proactive()
            self.save_profile(quiet=True)
            self.stop()
            self.drafts[self.character] = self.input.toPlainText()
        self.character, self.name = key, self.pet.character_name
        self.personality, self.personality_warning = load_personality(
            key, self.name, getattr(self.pet.character_pack, 'root', None))
        self.update_personality_label()
        persona, memory = self.store.profile(key, self.personality.persona)
        self.saved_profile = (persona, memory)
        draft_persona, draft_memory = self.profile_drafts.get(key, (persona, memory))
        self.persona_input.setPlainText(draft_persona)
        self.memory_input.setPlainText(draft_memory)
        self.input.setPlainText(self.drafts.get(key, ''))
        self.setWindowTitle(self.name + ' · 聊天')
        self.render_history()
        notices = [self.personality_warning] if self.personality_warning else []
        if key in self.profile_drafts:
            notices.append(self.name + '的人设或记忆尚未保存，编辑内容已恢复，请重试保存。')
        self.status.setText('；'.join(notices) or '已切换到' + self.name + '，人设与记忆按角色保存。')

    def update_personality_label(self):
        def brief(items):
            text = '、'.join(items)
            return text[:22] + ('…' if len(text) > 22 else '')
        personality = self.personality
        title = personality.name[:30]
        if self.personality_warning:
            title += '（使用备用人格）'
        self.personality_label.setText(
            '人格：' + title + '\n擅长：' + brief(personality.allowed)
            + '\n不擅长：' + brief(personality.decline))
        details = ('来源：' + personality.source + '\n版本：' + str(personality.version)
                   + '\n擅长：' + '、'.join(personality.allowed)
                   + '\n不擅长：' + '、'.join(personality.decline))
        if self.personality_warning:
            details += '\n' + self.personality_warning
        self.personality_label.setToolTip(details)

    def show_chat(self, settings=False):
        self.sync_character()
        if settings:
            self.tabs.setCurrentIndex(1)
        self.pet.toolbar.hide()
        self.pet.reveal_dock()
        from deskpet.pet.desktop import clamp_near
        clamp_near(self.pet, self)
        self.show()
        QTimer.singleShot(0, self.flush_partial)
        self.raise_()
        self.activateWindow()
        if self.tabs.currentIndex() == 0:
            self.input.setFocus()

    def choose_background(self):
        self.backgrounds.choose()

    def adjust_background_position(self):
        self.backgrounds.adjust()

    def clear_background(self):
        self.backgrounds.clear()

    def restore_persona(self):
        cursor = self.persona_input.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(self.personality.persona)
        cursor.endEditBlock()
        cursor.setPosition(0)
        self.persona_input.setTextCursor(cursor)
        self.status.setText('已套用角色默认人设，可继续编辑；Ctrl+Z 可撤销，记忆保持不变。')

    def save_profile(self, checked=False, quiet=False):
        profile = (self.persona_input.toPlainText(), self.memory_input.toPlainText())
        try:
            if profile != self.saved_profile:
                self.store.save_profile(self.character, *profile)
                self.saved_profile = profile
            self.profile_drafts.pop(self.character, None)
            self.profile_draft_names.pop(self.character, None)
        except (ValueError, sqlite3.Error) as error:
            self.profile_drafts[self.character] = profile
            self.profile_draft_names[self.character] = self.name
            self.status.setText('人设或记忆保存失败：' + str(error))
            return False
        if not quiet:
            self.status.setText('当前角色的人设和记忆已保存。')
        return True

    def current_config(self):
        config = ProviderConfig(self.url_input.text().strip(), self.model_input.text().strip(),
                                self.key_input.text().strip(), self.remember_key.isChecked(),
                                self.stream_toggle.isChecked())
        config.validate()
        return config

    def save_config(self):
        try:
            config = self.current_config()
            self.config_file.save(config)
            self.config = config
            self.balance_badge.refresh(force=True)
        except (ValueError, OSError) as error:
            self.status.setText('配置未保存：' + str(error))
            return False
        self.status.setText('配置已保存。' + ('' if config.remember_key else 'Key 仅用于本次运行。'))
        return True

    def set_busy(self, busy):
        self.send_button.setEnabled(not busy)
        self.test_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.input.setReadOnly(busy)

    def request_client(self):
        if self.client is None:
            from .remote import ChatClient
            self.client = ChatClient(self)
            self.client.partial.connect(self.on_partial)
            self.client.completed.connect(self.on_completed)
            self.client.failed.connect(self.on_failed)
            self.client.loadingChanged.connect(self.on_client_loading)
        return self.client

    def on_client_loading(self, loading):
        if self.pending or self.testing:
            self.status.setText('正在准备聊天连接，桌宠仍可互动…' if loading else
                                '正在测试连接…' if self.testing else '正在回复…')

    def test_connection(self):
        if self.pending or self.testing:
            return
        try:
            config = self.current_config()
            self.testing = True
            self.set_busy(True)
            self.status.setText('正在测试连接… 可在“聊天”页停止。')
            self.request_client().start(config, [dict(role='user', content='请只回复：连接成功')], test=True)
        except ValueError as error:
            self.on_failed(str(error))

    def restore_normal(self):
        self.stop()
        if not getattr(self.pet, 'dragging', False):
            end = getattr(self.pet, 'end_petting', None)
            if callable(end):
                end()
        from .actions import perform_action
        result = perform_action(self.pet, 'stop_action')
        self.status.setText(result.message)
        if self.pet.isVisible() and not self.pet.dragging:
            self.pet.bubble.say(result.message, 5000)

    def send_message(self):
        self.cancel_proactive()
        if self.pending or self.testing:
            return
        self.sync_character()
        user = self.input.toPlainText().strip()
        if not user:
            return
        if not self.save_profile(quiet=True):
            return
        try:
            if len(user) > 4000:
                raise ValueError('请输入 1～4000 字符的消息。')
            history = self.store.history(self.character, 12)
            refusal = request_refusal(user, history)
            if refusal:
                # Companion boundaries work even without an API, and never send
                # recognized technical tasks to the model to ask it to refuse.
                self.partial_text = ''
                self.pending = (self.character, user)
                self.input.clear()
                self.tabs.setCurrentIndex(0)
                self.on_completed(refusal, companion_reply=True)
                return
            from .actions import recognize_action, perform_action, available_actions
            action = recognize_action(user, self.name)
            if action:
                result = perform_action(self.pet, action)
                self.input.clear()
                try:
                    self.store.add_turn(self.character, user, result.message)
                    self.render_history()
                    self.status.setText('动作已执行。' if result.executed else '动作提示：' + result.message)
                except sqlite3.Error:
                    self.status.setText(result.message + '（聊天记录保存失败）')
                if self.pet.isVisible() and not self.pet.dragging and not getattr(self.pet, 'petting', False):
                    self.pet.bubble.say(result.message, 6500)
                return
            # Only saved provider settings are used for actual conversations.
            from . import music_actions
            direct_song = music_actions.explicit_song(user)
            if direct_song:
                self.pending = (self.character, user)
                self.pending_music_snapshot = music_actions.snapshot(self.pet)
                self.input.clear()
                self.tabs.setCurrentIndex(0)
                try:
                    result = perform_action(self.pet, direct_song[0], direct_song[1])
                except music_actions.MusicChoice as choice:
                    self.start_music_choice(choice.matches)
                    return
                self.on_completed(result.message, companion_reply=True)
                return
            self.config.validate()
            state = {'idle': '待机', 'sleep': '睡觉', 'phone': '玩手机',
                     'sing': '唱歌动作', 'listen': '陪伴听歌'}.get(self.pet.behavior.mode, '待机')
            snapshot = self.pet.panel.store.pet()
            context = f'时间：{datetime.now():%Y-%m-%d %H:%M}；活动：{state}；等级：{snapshot["level"]}。'
            recent = self.store.last_proactive(self.character)
            if recent:
                context += '；最近主动说过：' + recent
            if self.pet.playing:
                context += '正在播放：' + self.pet.panel.song_title.text()[:160]
            from . import music_actions
            context += music_actions.context(self.pet)
            messages = build_messages(self.persona_input.toPlainText(), self.memory_input.toPlainText(),
                                      history, user, context,
                                      personality=self.personality, actions=available_actions(self.pet))
            from .action_protocol import snapshot
            self.pending_action_context = snapshot(self.pet)
            self.pending_actions = tuple(available_actions(self.pet))
            self.pending_music_snapshot = music_actions.snapshot(self.pet)
            self.partial_text = ''
            self.pending = (self.character, user)
            self.input.clear()
            self.set_busy(True)
            self.tabs.setCurrentIndex(0)
            self.render_history(user, '')
            self.status.setText('正在回复…')
            self.request_client().start(self.config, messages)
        except (ValueError, sqlite3.Error) as error:
            self.on_failed(str(error))
            if not self.config.base_url or not self.config.model:
                self.tabs.setCurrentIndex(1)

    def render_history(self, user='', reply=''):
        messages = self.store.history(self.character)
        # Bound layout cost even when the last 60 messages are individually long.
        visible_messages = []
        remaining = 30000
        for message in reversed(messages):
            if visible_messages and len(message['content']) > remaining:
                break
            visible_messages.append(message)
            remaining -= len(message['content'])
        messages = list(reversed(visible_messages))
        if user:
            messages += [dict(role='user', content=user)]
        for message in messages:
            message['name'] = '你' if message['role']=='user' else self.name
        self.history_view.set_messages(messages, (self.name,reply or '正在想…') if user else None)
        self._reply_start = self.history_view.live_start
        self._reply_text = reply or '正在想…' if user else ''

    def on_partial(self, text):
        if self.music_choice is not None:
            return  # Candidate JSON is internal, not a chat reply.
        if self.pending:
            refusal = response_refusal(text)
            if refusal:
                # Inspect accumulated text before exposing this chunk. Abort any
                # remaining generation; only the companion reply is persisted.
                if self.client is not None:
                    self.client.cancel()
                self.partial_text = ''
                self.on_completed(refusal, companion_reply=True)
                return
            self.partial_text = text
            if not self.render_timer.isActive():
                self.render_timer.start(60)

    def flush_partial(self):
        if self.pending and self.isVisible() and self.tabs.currentIndex() == 0:
            visible, _ = parse_reply(self.partial_text, partial=True)
            visible = visible or '正在想…'
            if self._reply_start is None:
                self.render_history(self.pending[1], visible)
                return
            if visible == self._reply_text:
                return
            self.history_view.update_live(visible)
            self._reply_text = visible

    def on_completed(self, text, companion_reply=False):
        self.render_timer.stop()
        if not companion_reply:
            self.balance_badge.refresh()
        if self.music_choice is not None:
            self.finish_music_choice(text)
            return
        if self.testing:
            self.testing = False
            self.set_busy(False)
            self.status.setText('连接成功，模型已返回文字。请保存配置后聊天。')
            return
        if not self.pending:
            return
        character, user = self.pending
        if not companion_reply:
            refusal = response_refusal(text)
            if refusal:
                text = refusal
                companion_reply = True
        visible, tone = parse_reply(text)
        from .action_protocol import split_reply, snapshot, parameters
        _, action, action_error = split_reply(text)
        action_result = None
        if not companion_reply and (action or action_error):
            from .actions import perform_action, ActionResult
            from . import music_actions
            changed = (music_actions.snapshot(self.pet) != self.pending_music_snapshot
                       if action and action.startswith('music_') else snapshot(self.pet) != self.pending_action_context)
            if action_error:
                action_result = ActionResult(action_error)
            elif (self.pending_action_context is None or character != self.character
                    or not getattr(self, 'companion_mode_enabled', True)
                    or changed):
                action_result = ActionResult('刚才的状态已经改变了，这次先不做动作；需要的话再叫我一次吧。')
            elif action not in self.pending_actions:
                action_result = ActionResult('当前角色没有这个动作，换一个试试吧。')
            else:
                try:
                    action_result = perform_action(self.pet, action, parameters(text))
                except music_actions.MusicChoice as choice:
                    try:
                        self.start_music_choice(choice.matches)
                    except ValueError as error:
                        self.on_failed(str(error))
                    return
            if not action_result.executed or not visible or (action and action.startswith('music_')):
                visible = action_result.message
        if not visible:
            self.on_failed('模型只返回了情绪标签，没有文字，请重新发送。')
            return
        try:
            self.store.add_turn(character, user, visible)
        except sqlite3.Error:
            self.on_failed('聊天记录保存失败，请检查磁盘空间。')
            return
        self.pending = None
        self.pending_action_context = None
        self.pending_actions = ()
        self.pending_music_snapshot = None
        self.partial_text = ''
        self.set_busy(False)
        self.render_history()
        self.status.setText('已按日常陪伴范围回复。' if companion_reply else
                            '已回复。每次最多携带最近 6 轮、12000 字符的历史，另加人设与记忆。')
        if action_result is not None:
            self.status.setText('动作已执行。' if action_result.executed else '动作提示：' + action_result.message)
        # Never interrupt resting, dragging, feeding or another transient interaction.
        if (action_result is None and tone in ('开心', '欣喜') and not self.pet.behavior.layers
                and self.pet.behavior.mode == 'idle' and not self.pet.dragging
                and not getattr(self.pet, 'petting', False)
                and getattr(self.pet, 'press_point', None) is None
                and not self.pet.playing and self.pet.isVisible()):
            self.pet.react('happy', 1.8)
        if self.pet.isVisible() and not self.pet.dragging:
            self.pet.bubble.say(visible[:160] + ('…' if len(visible) > 160 else ''), 8000)

    def on_failed(self, message):
        self.render_timer.stop()
        self.music_choice = None
        if self.pending:
            self.input.setPlainText(self.pending[1])
        self.pending = None
        self.pending_action_context = None
        self.pending_actions = ()
        self.pending_music_snapshot = None
        self.testing = False
        self.set_busy(False)
        self.render_history()
        self.status.setText(message)

    def start_music_choice(self, matches):
        from .music_actions import choice_messages
        self.config.validate()
        self.music_choice = matches
        self.partial_text = ''
        self.set_busy(True)
        self.render_history(self.pending[1], '找到几个版本，正在挑选最合适的一首…')
        self.status.setText('正在根据你的描述选择歌曲…')
        self.request_client().start(self.config, choice_messages(self.pending[1], matches))

    def finish_music_choice(self, text):
        from .music_actions import chosen_item, play_item, snapshot
        matches, self.music_choice = self.music_choice, None
        if not self.pending:
            return
        if (self.pending[0] != self.character or not getattr(self,'companion_mode_enabled',True)
                or snapshot(self.pet) != self.pending_music_snapshot):
            self.on_failed('播放状态或歌单已经改变，这次未播放旧候选。')
            return
        try:
            selected = chosen_item(text, matches)
            result = play_item(self.pet, selected) if selected is not None else None
        except (ValueError, OSError) as error:
            self.on_failed(str(error))
            return
        self.on_completed(result.message if result else '候选里没有符合这次描述的版本，暂时不播放。', companion_reply=True)

    def stop(self):
        self.cancel_proactive()
        active = self.pending or self.testing
        if self.client is not None:
            self.client.cancel()
        if active:
            self.on_failed('已停止，本次未完成的对话未加入历史；输入已恢复。')

    def clear_history(self):
        answer = QMessageBox.question(self, '清空当前角色的聊天',
                                      '删除当前角色的聊天记录？人设和手动记忆会保留。')
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.stop()
        try:
            self.store.clear_history(self.character)
        except sqlite3.Error:
            self.status.setText('聊天记录删除失败，请检查磁盘权限。')
            return
        self.render_history()
        self.status.setText('当前角色的聊天记录已清空。')

    def save_profile_drafts(self):
        # Failed writes from other characters remain pending until storage recovers.
        try:
            for character, profile in list(self.profile_drafts.items()):
                self.store.save_profile(character, *profile)
                self.profile_drafts.pop(character, None)
                self.profile_draft_names.pop(character, None)
        except (ValueError, sqlite3.Error) as error:
            name = self.profile_draft_names.get(character, character)
            self.status.setText(name + '的人设或记忆保存失败：' + str(error))
            return False
        return True

    def closeEvent(self, event):
        self.stop()
        if not self.save_profile(quiet=True) or not self.save_profile_drafts():
            event.ignore()
            return
        event.accept()

    def shutdown(self):
        if not self.closed:
            self.balance_badge.shutdown()
            self.stop()
            self.work_panel.shutdown()
            self.companion_runtime.close()
            if self.client is not None:
                self.client.shutdown()
            self.save_profile(quiet=True)
            self.save_profile_drafts()
            self.store.close()
            self.closed = True
