"""Offline native work UI behavior, without API requests or real commands."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


class FakeClient(QObject):
    progress = Signal(str)
    event = Signal(dict)
    completed = Signal(str)
    failed = Signal(str)
    approval = Signal(dict)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.session_id = None
        self.starts = []
        self.followups = []
        self.answers = []
        self.closed = False
        self.ready = False

    def start(self, *args, **kwargs):
        self.starts.append((args, kwargs))
        self.busy = True
        self.busy_changed.emit(True)

    def can_resume(self):
        return bool(self.session_id)

    def followup(self, text):
        self.followups.append(text)
        return len(self.followups)

    def accept(self):
        self.session_id = 'session1'
        self.event.emit({'type':'session_ready','session_id':self.session_id})
        self.event.emit({'type':'input_received','seq':0})

    def approve(self, request_id, approved):
        self.answers.append((request_id, approved))

    def cancel(self):
        self.busy = False
        self.busy_changed.emit(False)

    def shutdown(self):
        self.closed = True
        self.cancel()


class WorkPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from deskpet.chat.work_panel import WorkPanel
        with patch('deskpet.chat.work_client.WorkClient', FakeClient):
            self.panel = WorkPanel(lambda: 'saved-config')
        self.panel.folder.setText('test-workspace')
        self.panel.prompt.setPlainText('edit file')

    def tearDown(self):
        self.panel.shutdown()
        self.panel.deleteLater()

    def test_busy_duplicate_hide_and_retry(self):
        p = self.panel
        p.start(); p.start(); p.hide()
        self.assertEqual(len(p.client.starts), 1)
        self.assertTrue(p.is_running)
        self.assertTrue(p.start_button.isEnabled())
        self.assertFalse(p.prompt.isReadOnly())
        self.assertEqual(p.prompt.toPlainText(), '')
        p.client.cancel(); p.client.failed.emit('failure')
        self.assertTrue(p.start_button.isEnabled())
        self.assertEqual(p.prompt.toPlainText(), 'edit file')
        p.start()
        self.assertEqual(len(p.client.starts), 2)

    def test_multiple_followups_and_late_receipt_preserve_new_draft_and_approval(self):
        p = self.panel
        p.start()
        p.request_approval({'id':'1', 'arguments':{'command':'test'}})
        for text in ('先只读', '先看文档'):
            p.prompt.setPlainText(text)
            p.start()
            self.assertEqual(p.prompt.toPlainText(), '')
        p.prompt.setPlainText('草稿')
        p.client.accept()
        p.client.event.emit({'type':'input_received', 'seq':1})
        self.assertEqual(p.approval_id, '1')
        self.assertEqual(p.client.followups, ['先只读', '先看文档'])
        self.assertEqual(len(p.client.starts), 1)
        p.client.failed.emit('后端退出')
        self.assertEqual(p.prompt.toPlainText(), '草稿')
        self.assertIn('先看文档', p.events.toPlainText())

    def test_work_bubbles_render_markdown_after_restore_and_keep_user_text_literal(self):
        p = self.panel
        reply = '# 结果\n\n**加粗**\n\n- 事项\n\n```py\nif x:\n    pass\n```\n\n![图](file:///absent.png)'
        p.log.append_message('user', '**原样**')
        p.log.append_message('assistant', reply)
        p.log.set_messages(p.log.messages)
        doc = p.log.document()
        self.assertIn('**原样**', doc.toPlainText())
        self.assertEqual(doc.find('结果').blockFormat().headingLevel(), 1)
        self.assertGreaterEqual(doc.find('加粗').charFormat().fontWeight(), 600)
        self.assertIsNotNone(doc.find('事项').currentList())
        self.assertIn('    pass', doc.toPlainText())
        self.assertNotIn('<img ', doc.toHtml())
        self.assertEqual(p.log.messages[-1]['content'], reply)

    def test_composer_enter_shift_enter_and_chinese_composition(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QInputMethodEvent
        from PySide6.QtTest import QTest
        p = self.panel
        p.prompt.setPlainText('检查项目')
        p.prompt.moveCursor(p.prompt.textCursor().MoveOperation.End)
        QTest.keyClick(p.prompt, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(p.prompt.toPlainText(), '检查项目\n')
        self.assertEqual(p.client.starts, [])
        QApplication.sendEvent(p.prompt, QInputMethodEvent('zhong', []))
        QTest.keyClick(p.prompt, Qt.Key_Return)
        self.assertEqual(p.client.starts, [])
        commit = QInputMethodEvent()
        commit.setCommitString('中')
        QApplication.sendEvent(p.prompt, commit)
        QTest.keyClick(p.prompt, Qt.Key_Return)
        self.assertEqual(len(p.client.starts), 1)
        QTest.keyClick(p.prompt, Qt.Key_Return)
        self.assertEqual(len(p.client.starts), 1)

    def test_scrolling_messages_and_opening_approval_keep_composer_at_bottom(self):
        p = self.panel
        p.folder_row.hide()
        p.resize(510, 620)
        p.show()
        self.app.processEvents()
        position = p.composer.geometry().bottom()
        for index in range(30):
            p.log.append_message('assistant', '较长的工作结果 ' * 20)
        self.app.processEvents()
        p.log.verticalScrollBar().setValue(0)
        self.assertEqual(p.composer.geometry().bottom(), position)
        p.start()
        p.request_approval({'id': 'geometry', 'toolName': 'pwsh',
                            'arguments': {'command': 'test fixture'}})
        self.app.processEvents()
        self.assertTrue(p.approval_box.isVisible())
        self.assertEqual(p.composer.geometry().bottom(), position)
        self.assertLess(p.approval_box.geometry().bottom(), p.composer.geometry().top())
        self.assertGreater(p.log.height(), 0)

    def test_setup_progress_visible_without_opening_tool_details(self):
        p = self.panel; p.start()
        p.client.event.emit({'type': 'runtime_setup', 'text': '正在下载 Node.js：10 / 36 MB'})
        self.assertEqual(p.state.text(), '正在下载 Node.js：10 / 36 MB')
        self.assertTrue(p.stop_button.isEnabled())
        p.client.progress.emit('正在启动工作后端…')
        self.assertEqual(p.state.text(), '工作中…')

    def test_auto_approval_requires_confirmation_and_keeps_high_risk_manual(self):
        from PySide6.QtWidgets import QMessageBox
        p=self.panel
        self.assertFalse(p.auto_approve.isChecked())
        with patch('deskpet.chat.work_panel.QMessageBox.warning',return_value=QMessageBox.No):
            p.auto_approve.setChecked(True)
        self.assertFalse(p.auto_approve.isChecked())
        with patch('deskpet.chat.work_panel.QMessageBox.warning',return_value=QMessageBox.Yes) as warning:
            p.auto_approve.setChecked(True)
        self.assertIn('项目文件夹以外',warning.call_args.args[2])
        p.start()
        self.assertTrue(p.client.starts[-1][1]['auto_approve'])
        self.assertFalse(p.auto_approve.isEnabled())
        p.request_approval(dict(id='high-risk',toolName='pwsh',arguments={'command':'risky fixture'}))
        self.assertEqual(p.client.answers,[])
        p.answer(False)
        self.assertEqual(p.client.answers,[('high-risk',False)])
        p.client.cancel();p.auto_approve.setChecked(False)
        p.prompt.setPlainText('next task');p.start()
        self.assertFalse(p.client.starts[-1][1]['auto_approve'])

    def test_startup_failure_keeps_input_and_direct_retry_creates_new_session(self):
        p=self.panel
        p.start()
        self.assertEqual(p.prompt.toPlainText(),'')
        self.assertFalse(p.continue_session.isChecked())
        p.client.failed.emit('initialize timed out');p.client.cancel()
        self.assertEqual(p.prompt.toPlainText(),'edit file')
        p.start()
        self.assertIsNone(p.client.starts[-1][1]['session_id'])
        p.client.accept()
        self.assertTrue(p.continue_session.isChecked())
        self.assertEqual(p.prompt.toPlainText(),'')

    def test_new_session_failure_does_not_replace_old_session(self):
        p=self.panel;p.client.session_id='old123';p.session_folder=p.folder.text()
        p.continue_session.setChecked(False)
        p.start();p.client.failed.emit('initialize timed out');p.client.cancel()
        self.assertEqual(p.client.session_id,'old123')
        self.assertFalse(p.continue_session.isChecked())
        p.start()
        self.assertIsNone(p.client.starts[-1][1]['session_id'])

    def test_explicit_approval_original_parameters_and_event(self):
        p = self.panel; p.start()
        request = dict(id='a',toolName='shell',arguments={'command':'echo <raw> && more'},reason='request')
        p.client.approval.emit(request)
        self.assertIn('echo <raw> && more',p.approval_text.toPlainText())
        self.assertEqual(p.client.answers, [])
        p.answer(False); p.answer(True)
        self.assertEqual(p.client.answers,[('a',False)])
        p.client.approval.emit(dict(request,id='b'));p.answer(True)
        self.assertEqual(p.client.answers[-1],('b',True))
        p.client.event.emit(dict(type='session.event',event={'type':'file.changed','data':{'path':'a.txt'}}))
        self.assertIn('a.txt',p.events.toPlainText())

    def test_continue_session_and_shutdown(self):
        p=self.panel;p.start();p.client.accept();p.client.cancel()
        p.prompt.setPlainText('continue');p.continue_session.setChecked(True);p.start()
        self.assertEqual(p.client.starts[-1][1]['session_id'],'session1')
        p.client.cancel();p.folder.setText('different');p.start()
        self.assertEqual(len(p.client.starts),2)
        p.shutdown();self.assertTrue(p.client.closed)

    def test_official_approval_waits_for_matching_session_command(self):
        p = self.panel
        p.start()
        p.request_approval({'id':'approval-1', 'sessionId':'one', 'callId':'call-1', 'toolName':'pwsh', 'reason':'test'})
        self.assertFalse(p.allow.isEnabled())
        p.answer(True)
        self.assertEqual(p.client.answers, [])
        def call(session):
            p.on_event({'type':'session.event', 'sessionId':session, 'event':{'type':'tool/call', 'data':{
                'callId':'call-1', 'name':'pwsh', 'arguments':'{"command":"Write-Output <exact>"}'}}})
        call('other')
        self.assertFalse(p.allow.isEnabled())
        call('one')
        self.assertTrue(p.allow.isEnabled())
        self.assertIn('Write-Output <exact>', p.approval_text.toPlainText())
        p.answer(True)
        self.assertEqual(p.client.answers, [('approval-1', True)])

    def test_official_approval_after_call_shows_exact_arguments(self):
        p = self.panel
        p.start()
        p.on_event({'type':'session.event', 'sessionId':'one', 'event':{'type':'tool/call', 'data':{
            'callId':'call-1', 'name':'pwsh', 'arguments':{'command':'Get-Content result.json'}}}})
        p.request_approval({'id':'approval-1', 'sessionId':'one', 'callId':'call-1', 'toolName':'pwsh'})
        self.assertTrue(p.allow.isEnabled())
        self.assertIn('Get-Content result.json', p.approval_text.toPlainText())


    def test_parallel_approval_fifo_deduplication_and_stop(self):
        p=self.panel;p.start()
        for identifier in ('a','b','a','c'):
            p.client.approval.emit(dict(id=identifier,toolName='shell',arguments={'command':identifier}))
        self.assertEqual(p.approval_id,'a')
        self.assertEqual([r['id'] for r in p.approval_queue],['b','c'])
        p.answer(True);self.assertEqual(p.approval_id,'b')
        p.answer(False);self.assertEqual(p.approval_id,'c')
        self.assertEqual(p.client.answers,[('a',True),('b',False)])
        p.stop();self.assertIsNone(p.approval_id)
        self.assertEqual(p.approval_queue,[])

    def test_terminal_state_survives_busy_signal_order(self):
        p=self.panel;p.start()
        p.client.completed.emit('done')
        self.assertEqual(p.state.text(),'工作完成')
        p.client.cancel()
        self.assertEqual(p.state.text(),'工作完成')
        p.start();p.client.cancel();p.client.failed.emit('error')
        self.assertIn('工作已结束',p.state.text())
        self.assertTrue(p.start_button.isEnabled())

    def test_token_events_do_not_flood_summary_and_details_are_optional(self):
        p=self.panel
        for index in range(20):
            p.on_event(dict(type='session.event',event={'type':'text.delta','data':{'text':str(index)}}))
        self.assertEqual(p.events.toPlainText(),'')
        self.assertFalse(p.details_toggle.isChecked())
        p.on_event(dict(type='session.event',event={'type':'file.changed','data':{'path':'a.txt'}}))
        self.assertIn('文件变化',p.events.toPlainText())
        self.assertNotIn('session.event',p.events.toPlainText())
        self.assertIn('text.delta',p.event_details.toPlainText())

    def test_official_tool_calls_results_and_approval_progress(self):
        p=self.panel;p.start()
        def emit(kind,data):
            p.on_event({'type':'session.event','event':{'type':kind,'data':data}})
        emit('tool/call',{'callId':'r','name':'read','arguments':'{"path":"README.md"}'})
        self.assertIn('准备读取文件',p.events.toPlainText())
        self.assertNotIn('文件变化',p.events.toPlainText())
        emit('tool/result',{'message':{'toolCallId':'r','isError':False,'content':[]},'meta':{'operation':'read','path':'README.md'}})
        self.assertIn('读取完成 · read · README.md',p.events.toPlainText())
        emit('tool/call',{'callId':'w','name':'write','arguments':'{"path":"new.txt"}'})
        self.assertNotIn('文件已写入',p.events.toPlainText())
        emit('tool/result',{'message':{'toolCallId':'w','isError':True,'content':[{'type':'text','text':'permission denied'}]},'meta':{'path':'new.txt'}})
        self.assertIn('permission denied',p.events.toPlainText())
        self.assertNotIn('文件已写入',p.events.toPlainText())
        emit('tool/call',{'callId':'w2','name':'write','arguments':'{"path":"ok.txt"}'})
        emit('tool/result',{'message':{'toolCallId':'w2','isError':False,'content':[]},'meta':{'operation':'create','path':'ok.txt'}})
        self.assertIn('文件已写入 · write · ok.txt',p.events.toPlainText())
        original=p.events.toPlainText()
        emit('assistant/message',{'stream':[{'type':'text-chunks','texts':['token']}]})
        self.assertEqual(p.events.toPlainText(),original)
        p.request_approval({'id':'pending','arguments':{'command':'test'}})
        waiting=p.state.text();p.on_progress('正在思考')
        self.assertEqual(p.state.text(),waiting)
        self.assertIn('正在思考',p.events.toPlainText())
        self.assertNotIn('正在思考',p.log.toPlainText())
        self.assertIn('token',p.log.toPlainText())



if __name__ == '__main__':
    unittest.main()
