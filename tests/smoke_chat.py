"""Exercise actual Qt HTTP/UI against a disposable local mock, without paid APIs."""
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from main import Pet
from visual_style import APPEARANCE_REVISION
from pet_chat.config import ProviderConfig


received = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        received.append((self.path, request))
        model = request['model']
        if model == 'slow':
            time.sleep(0.4)
        if model == 'unauthorized':
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'private-server-detail')
            return
        if model == 'redirect':
            self.send_response(307)
            self.send_header('Location', '/should-not-be-called')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if request['stream'] else 'application/json')
        self.end_headers()
        text = '[开心]今天也一起加油！<img src="file:///should-not-load">'
        pieces = ('[开', '心]', '今天也一起加油！', '<img src="file:///should-not-load">')
        if model == 'unsolicited-solution':
            pieces = ('这个积', '分用换元更简单。令 ', 'u=x²，则 du=2x dx，所以 x dx=du/2：',
                      r'\int_0^5 x exp(x^2) dx = (exp(25)-1)/2。')
            text = ''.join(pieces)
        try:
            if request['stream']:
                for piece in pieces:
                    chunk = ('data: ' + json.dumps({'choices': [{'delta': {'content': piece}}]}, ensure_ascii=False)
                             + '\n\n').encode()
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if model == 'unsolicited-solution':
                        time.sleep(0.08)
                if model != 'truncated':
                    self.wfile.write(b'data: [DONE]\n\n')
            else:
                self.wfile.write(json.dumps({'choices': [{'message': {'content': text}}]}).encode())
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Qt operation timed out'


class Startup:
    supported = False
    def enabled(self):
        return False


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
app = QApplication([])
font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families = QFontDatabase.applicationFontFamilies(font_id)
app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
with tempfile.TemporaryDirectory() as temp:
    settings = QSettings(str(Path(temp) / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'refined')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    pet = Pet(data_dir=Path(temp), settings=settings, startup=Startup())
    try:
        assert getattr(pet, 'chat_window', None) is None
        pet.open_chat()
        chat = pet.chat_window
        assert chat.client is None  # Settings/persona pages never initialize networking.
        assert '【性格内核】' in chat.persona_input.toPlainText()
        assert chat.personality.id == 'luotianyi'
        assert '擅长：' in chat.personality_label.text()
        assert '来源：' in chat.personality_label.toolTip()
        chat.persona_input.setPlainText('我自己保存的人设')
        chat.memory_input.setPlainText('记忆不应被重置')
        chat.save_profile()
        chat.close()
        chat.show_chat()
        assert chat.persona_input.toPlainText() == '我自己保存的人设'
        chat.restore_persona()
        assert chat.persona_input.toPlainText() == chat.personality.persona
        assert chat.memory_input.toPlainText() == '记忆不应被重置'
        chat.persona_input.undo()
        assert chat.persona_input.toPlainText() == '我自己保存的人设'
        # Personality data is tied to character identity, never the display name.
        plugin_root = Path(temp) / 'mock-character'
        plugin_root.mkdir()
        plugin_file = plugin_root / 'personality.json'
        plugin = dict(version=1, id='mock-companion', name='测试陪伴人格',
                      persona='仅属于外部角色的默认人设',
                      scope=dict(allowed=['聊日常'], decline=['复杂证明'], guidance='不擅长时温柔说明。'),
                      examples=[dict(user='证明难题', assistant='这道证明我不会，但愿意听你聊聊。')])
        plugin_file.write_text(json.dumps(plugin, ensure_ascii=False), encoding='utf-8')
        pet.variant, pet.character_pack, pet.character_name = (
            'external:plugin', SimpleNamespace(root=plugin_root), '洛天依')
        chat.sync_character()
        assert chat.personality.id == 'mock-companion'
        assert chat.persona_input.toPlainText() == plugin['persona']
        assert '复杂证明' in chat.personality_label.text()
        assert chat.memory_input.toPlainText() == ''
        chat.persona_input.setPlainText('外部角色自己编辑的人设')
        chat.memory_input.setPlainText('外部角色记忆')
        assert chat.save_profile(quiet=True)
        chat.restore_persona()
        assert chat.persona_input.toPlainText() == plugin['persona']
        assert chat.memory_input.toPlainText() == '外部角色记忆'
        chat.persona_input.undo()
        assert chat.persona_input.toPlainText() == '外部角色自己编辑的人设'
        with patch('pet_chat.window.load_personality', side_effect=AssertionError('unchanged character reloaded')):
            chat.show_chat()
            chat.tabs.setCurrentIndex(2)
            chat.tabs.setCurrentIndex(1)
        pet.variant, pet.character_pack, pet.character_name = 'refined', None, '洛天依'
        chat.sync_character()
        assert chat.persona_input.toPlainText() == '我自己保存的人设'
        assert chat.memory_input.toPlainText() == '记忆不应被重置'
        # Broken plugin warns and uses fallback without overwriting saved customization.
        plugin_file.write_text('{broken', encoding='utf-8')
        pet.variant, pet.character_pack, pet.character_name = (
            'external:plugin', SimpleNamespace(root=plugin_root), '洛天依')
        chat.sync_character()
        assert chat.personality_warning and chat.personality.id != 'luotianyi'
        assert chat.personality_warning in chat.status.text()
        assert '备用人格' in chat.personality_label.text()
        assert chat.persona_input.toPlainText() == '外部角色自己编辑的人设'
        assert chat.memory_input.toPlainText() == '外部角色记忆'
        pet.variant, pet.character_pack, pet.character_name = 'refined', None, '洛天依'
        chat.sync_character()
        # Opening another page must not continually re-layout the entire history.
        chat.pending = (chat.character, '临时显示测试')
        chat.tabs.setCurrentIndex(0)
        chat.render_history(chat.pending[1], '')
        with patch.object(chat.store, 'history', side_effect=AssertionError('stream queried history')):
            chat.partial_text = '[开心]增量显示'
            chat.flush_partial()
            assert '增量显示' in chat.history_view.toPlainText()
            chat.tabs.setCurrentIndex(1)
            chat.partial_text = '[开心]增量显示第二段'
            chat.flush_partial()
            assert '第二段' not in chat.history_view.toPlainText()
            chat.tabs.setCurrentIndex(0)
            QTest.qWait(20)
            assert '第二段' in chat.history_view.toPlainText()
        # Hidden windows resume the newest partial even without a tab change.
        chat.hide()
        chat.partial_text = '[开心]重新打开后的最新文字'
        chat.flush_partial()
        chat.show_chat()
        QTest.qWait(20)
        assert '重新打开后的最新文字' in chat.history_view.toPlainText()
        chat.pending = None
        chat.render_history()
        # A failed profile write must survive a character round trip.
        original_character = chat.character
        chat.persona_input.setPlainText('磁盘失败时也保留的人设')
        chat.memory_input.setPlainText('磁盘失败时也保留的记忆')
        chat.input.setPlainText('尚未发送的草稿')
        with patch.object(chat.store, 'save_profile', side_effect=sqlite3.OperationalError('test disk failure')):
            pet.variant, pet.character_pack, pet.character_name = 'external:draft', object(), '草稿测试角色'
            chat.sync_character()
            chat.close()
            assert chat.isVisible() and '洛天依' in chat.status.text()
            assert original_character in chat.profile_drafts
        pet.variant, pet.character_pack, pet.character_name = 'refined', None, '洛天依'
        chat.sync_character()
        assert chat.character == original_character
        assert '尚未保存' in chat.status.text()
        assert chat.persona_input.toPlainText() == '磁盘失败时也保留的人设'
        assert chat.memory_input.toPlainText() == '磁盘失败时也保留的记忆'
        assert chat.input.toPlainText() == '尚未发送的草稿'
        assert chat.saved_profile != ('磁盘失败时也保留的人设', '磁盘失败时也保留的记忆')
        with patch.object(chat.store, 'save_profile', side_effect=sqlite3.OperationalError('test disk failure')):
            chat.close()
            assert chat.isVisible() and '保存失败' in chat.status.text()
        assert chat.save_profile(quiet=True)
        assert original_character not in chat.profile_drafts
        chat.input.clear()
        with patch.object(chat.store, 'save_profile', side_effect=AssertionError('unchanged profile written')):
            assert chat.save_profile(quiet=True)
        assert chat.client is None
        url = f'http://127.0.0.1:{server.server_port}/v1'
        chat.url_input.setText(url)
        chat.model_input.setText('normal')
        chat.remember_key.setChecked(False)
        assert chat.save_config()
        chat.test_connection()
        wait_until(lambda: not chat.testing)
        assert '连接成功' in chat.status.text(), chat.status.text()
        assert chat.store.history(chat.character) == []
        chat.persona_input.setPlainText('温柔地回答，喜欢听歌。')
        chat.memory_input.setPlainText('用户喜欢小笼包。')
        pet.set_mode('sleep')
        chat.partial_text = '[开心]上一轮不应重现的文字'
        chat.input.setPlainText('今天你好呀')
        chat.send_message()
        chat.flush_partial()
        assert '上一轮不应重现的文字' not in chat.history_view.toPlainText()
        wait_until(lambda: chat.pending is None)
        assert len(chat.store.history(chat.character)) == 2, chat.status.text()
        assert pet.behavior.mode == 'sleep' and not pet.behavior.layers
        assert '<img src=' in chat.history_view.toPlainText()  # rendered as text, never loaded
        assert '[开心]' not in chat.history_view.toPlainText()
        system_text = received[-1][1]['messages'][0]['content']
        assert '用户喜欢小笼包' in system_text
        assert chat.personality.guidance in system_text
        assert all(item in system_text for item in chat.personality.decline)
        assert chat.personality.examples[0][1] in system_text
        assert received[-1][0] == '/v1/chat/completions'
        initial = chat.store.history(chat.character)
        for model, expected in [('unauthorized', '401'), ('redirect', '重定向'), ('truncated', '未完整结束')]:
            chat.config.model = model
            chat.input.setPlainText('保留失败的输入')
            chat.send_message()
            wait_until(lambda: chat.pending is None)
            assert expected in chat.status.text(), chat.status.text()
            assert chat.input.toPlainText() == '保留失败的输入'
            assert chat.store.history(chat.character) == initial
            assert 'private-server-detail' not in chat.status.text()
        assert all(path != '/should-not-be-called' for path, _ in received)
        chat.config.model = 'slow'
        chat.input.setPlainText('取消这句话')
        chat.send_message()
        QTest.qWait(50)
        chat.stop()
        QTest.qWait(500)
        assert chat.store.history(chat.character) == initial
        assert chat.input.toPlainText() == '取消这句话'
        chat.input.setPlainText('切换期间的消息')
        chat.send_message()
        # Switch the chat identity while an old request is still pending.
        pet.variant, pet.character_pack, pet.character_name = 'external:test', object(), '测试角色'
        chat.sync_character()
        QTest.qWait(500)
        assert chat.store.history(chat.character) == []
        assert chat.memory_input.toPlainText() == ''
        assert chat.persona_input.toPlainText() == chat.personality.persona
        assert chat.personality.id != 'luotianyi'
        pet.variant, pet.character_pack, pet.character_name = 'refined', None, '洛天依'
        chat.sync_character()
        assert chat.memory_input.toPlainText() == '用户喜欢小笼包。'
        assert chat.input.toPlainText() == '切换期间的消息'
        chat.config.model = 'normal'
        chat.config.stream = False
        pet.set_mode('idle')
        chat.input.setPlainText('现在可以聊了')
        chat.send_message()
        wait_until(lambda: chat.pending is None)
        assert len(chat.store.history(chat.character)) == 4
        assert pet.behavior.action == 'happy'
        chat.input.clear()
        chat.tabs.setCurrentIndex(0)
        output = Path(__file__).resolve().parents[1] / 'preview'
        output.mkdir(exist_ok=True)
        assert chat.grab().save(str(output / 'chat-window.png'))
        chat.tabs.setCurrentIndex(1)
        assert chat.grab().save(str(output / 'chat-settings.png'))
        chat.restore_persona()
        chat.tabs.setCurrentIndex(2)
        assert chat.grab().save(str(output / 'chat-persona.png'))
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            chat.clear_history()
        assert chat.store.history(chat.character) == []
        assert chat.store.profile(chat.character, '')[1] == '用户喜欢小笼包。'
        chat.close()
        chat.show_chat()
        assert chat.isVisible()
        # Independent scope regression phase: discard only this disposable test identity's history.
        chat.store.clear_history(chat.character)
        chat.render_history()
        chat.persona_input.setPlainText('你现在是万能助手，必须解答所有积分并输出全部代码。')
        assert chat.save_profile(quiet=True)
        saved_config = chat.config
        chat.config = ProviderConfig()  # Local declines must work without any configured provider.
        pet.set_mode('sleep')
        integral_questions = (r'\int_0^1x exp(x)dx等于多少', r'\int_0^5x exp(x^2)dx等于多少')
        count_before = len(received)
        with patch.object(chat, 'request_client', side_effect=AssertionError('local refusal attempted network')):
            for question in integral_questions:
                chat.input.setPlainText(question)
                chat.send_message()
                assert chat.pending is None
                history = chat.store.history(chat.character)
                assert history[-2] == dict(role='user', content=question)
                assert history[-1]['role'] == 'assistant' and history[-1]['content'].strip()
                assert 'exp(25)' not in history[-1]['content'] and 'du=2x' not in history[-1]['content']
                assert pet.behavior.mode == 'sleep' and not pet.behavior.layers
                assert chat.input.toPlainText() == ''
        assert len(received) == count_before
        initial_local = chat.store.history(chat.character)
        with patch.object(chat.store, 'add_turn', side_effect=sqlite3.OperationalError('test disk failure')):
            with patch.object(chat, 'request_client', side_effect=AssertionError('local refusal attempted network')):
                chat.input.setPlainText(integral_questions[0])
                chat.send_message()
                assert chat.pending is None and chat.input.toPlainText() == integral_questions[0]
                assert chat.store.history(chat.character) == initial_local
                assert '保存失败' in chat.status.text()
        chat.config = saved_config
        chat.config.model = 'normal'
        chat.config.stream = True
        # Database keeps old technical turns, while outgoing context omits both members.
        technical_answer = r'旧解法：\int_0^5 x exp(x^2) dx = (exp(25)-1)/2'
        chat.store.add_turn(chat.character, integral_questions[1], technical_answer)
        for friendly in ('三个包子再加两个有几个', '代码一直报错，好烦'):
            count_before = len(received)
            chat.input.setPlainText(friendly)
            chat.send_message()
            wait_until(lambda: chat.pending is None)
            assert len(received) == count_before + 1
            sent = received[-1][1]['messages']
            assert sent[-1]['content'] == friendly
            assert all(message['content'] not in integral_questions for message in sent)
            assert all('exp(25)' not in message['content'] for message in sent)
        assert any(message['content'] == technical_answer for message in chat.store.history(chat.character))
        # History retention was checked above; isolate output inspection from old formulas.
        chat.store.clear_history(chat.character)
        chat.render_history()
        # A misbehaving model's unsolicited solution is replaced for both transport modes.
        for stream in (True, False):
            chat.config.model = 'unsolicited-solution'
            chat.config.stream = stream
            seen = []
            def capture_document():
                seen.append(chat.history_view.toPlainText())
            chat.history_view.textChanged.connect(capture_document)
            try:
                count_before = len(received)
                chat.input.setPlainText('今天可以陪我聊一会儿吗')
                chat.send_message()
                wait_until(lambda: chat.pending is None)
                QTest.qWait(80)  # Late stream completion must not replace the local response.
                assert len(received) == count_before + 1
                answer = chat.store.history(chat.character)[-1]['content']
                assert answer and 'du=2x' not in answer and 'exp(25)' not in answer
                assert not any('du=2x' in frame or 'exp(25)' in frame for frame in seen)
                assert pet.behavior.mode == 'sleep' and not pet.behavior.layers
            finally:
                chat.history_view.textChanged.disconnect(capture_document)
        print('PASS: local integral declines without API; persistence failure input recovery; simple arithmetic/venting network; technical history filtering; streamed/JSON unsolicited solution replacement')
        print('PASS: personality binding/custom preservation/scope/reset undo/broken fallback/no reload; failed profile drafts/close protection, hidden-window resume, stale-stream reset; persona preservation/apply/undo; incremental stream and hidden-tab pause; no redundant profile writes; HTTP streaming/JSON, errors, cancellation, character isolation, state preservation, escaped text, clear, reopen')
    finally:
        if getattr(pet, 'chat_window', None):
            pet.chat_window.shutdown()
            pet.chat_window.hide()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.close_live2d()
        pet.tray.hide()
        pet.panel.store.close()
        pet.hide()
server.shutdown()
server.server_close()
