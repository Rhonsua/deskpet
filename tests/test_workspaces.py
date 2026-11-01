import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from tests.test_work_panel import FakeClient
from deskpet.chat.workspaces import Workspaces

class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_projects_restore_history_drafts_sessions_and_selection(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            a=w.add_project(str(Path(folder)/'a'));a.client.session_id='a123';a.continue_session.setChecked(True);a.prompt.setPlainText('draft A');a.log.setPlainText('answer A')
            a.restore_auto_approve(True)
            b=w.add_project(str(Path(folder)/'b'));b.client.session_id='b123';b.prompt.setPlainText('draft B')
            w.save();w.shutdown()
            restored=Workspaces(lambda:'config',folder)
            pages=list(restored.pages.values())
            self.assertEqual(restored.stack.currentWidget().prompt.toPlainText(),'draft B')
            self.assertEqual(pages[0].log.toPlainText(),'answer A')
            self.assertEqual(pages[0].client.session_id,'a123')
            self.assertTrue(pages[0].continue_session.isChecked())
            self.assertTrue(pages[0].auto_approve.isChecked())
            self.assertFalse(pages[1].auto_approve.isChecked())
            self.assertFalse(restored.is_running)
            restored.shutdown()

    def test_failed_legacy_session_restores_as_retryable_without_losing_history(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.ROOT',Path(folder)):
            path=Path(folder)/'work-projects.json'
            path.write_text(json.dumps({'version':1,'projects':[{
                'folder':folder,'session_id':'failed123','draft':'这是个什么项目',
                'log':'initialize timed out waiting for DeepSeek Harness runtime',
                'running':False}]}),encoding='utf8')
            w=Workspaces(lambda:'config',folder)
            p=w.stack.currentWidget()
            self.assertFalse(p.continue_session.isChecked())
            self.assertIsNone(p.client.session_id)
            self.assertEqual(p.prompt.toPlainText(),'这是个什么项目')
            self.assertIn('initialize timed out',p.log.toPlainText())
            self.assertIn('直接开始',p.state.text())
            w.shutdown()

    def test_pending_task_survives_project_switch_and_restart(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            a=w.add_project(folder);a.prompt.setPlainText('pending task');a.start()
            w.add_project(str(Path(folder)/'other'))
            w.shutdown()
            w=Workspaces(lambda:'config',folder)
            a=list(w.pages.values())[0]
            self.assertEqual(a.prompt.toPlainText(),'pending task')
            self.assertFalse(a.continue_session.isChecked())
            self.assertEqual(a.client.starts,[])
            w.shutdown()
    def test_background_project_owns_events_and_blocks_second_execution(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            a=w.add_project(folder);a.prompt.setPlainText('task A');a.start()
            b=w.add_project(str(Path(folder)/'b'));b.prompt.setPlainText('task B');b.start()
            self.assertEqual(len(b.client.starts),0)
            a.client.progress.emit('A progress')
            self.assertIn('A progress',a.events.toPlainText());self.assertNotIn('A progress',b.events.toPlainText())
            self.assertTrue(w.is_running)
            w.save()
            data=json.loads(w.path.read_text('utf8'));self.assertTrue(data['projects'][0]['conversations'][0]['running'])
            w.shutdown()

    def test_multiple_conversations_keep_sessions_drafts_and_selected_thread(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            first=w.add_project(folder);first.client.session_id='first123'
            first.continue_session.setChecked(True)
            first.log.append_message('user','先看看项目结构')
            first.prompt.setPlainText('第一段草稿')
            second=w.new_conversation();second.client.session_id='second456'
            second.continue_session.setChecked(True)
            second.prompt.setPlainText('第二段草稿')
            self.assertEqual(len(w.pages),2)
            self.assertEqual(w.projects.topLevelItem(0).childCount(),2)
            w.select_conversation(first.conversation_id)
            w.shutdown()
            restored=Workspaces(lambda:'config',folder)
            a,b=list(restored.pages.values())
            self.assertIs(restored.stack.currentWidget(),a)
            self.assertEqual(a.client.session_id,'first123')
            self.assertEqual(b.client.session_id,'second456')
            self.assertEqual(a.prompt.toPlainText(),'第一段草稿')
            self.assertEqual(b.prompt.toPlainText(),'第二段草稿')
            self.assertIn('先看看项目结构',a.log.toPlainText())
            self.assertEqual(b.log.messages,[])
            restored.shutdown()

    def test_new_button_reuses_empty_conversation_in_current_project(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            first=w.add_project(folder)
            w.new_button.click();w.new_compact.click()
            self.assertEqual(len(w.pages),1)
            self.assertIs(w.stack.currentWidget(),first)
            first.log.append_message('user','先看看项目结构')
            empty=w.new_conversation()
            other=w.add_project(str(Path(folder)/'other'))
            w.new_button.click()
            self.assertIs(w.stack.currentWidget(),other)
            w.select_conversation(first.conversation_id)
            w.search.setText('找不到的对话')
            w.new_button.click()
            self.assertIs(w.stack.currentWidget(),empty)
            self.assertEqual(len(w.pages),3)
            self.assertEqual(w.search.text(),'')
            empty.prompt.setPlainText('还没发出的草稿')
            fresh=w.new_conversation()
            self.assertIsNot(fresh,empty)
            self.assertEqual(empty.prompt.toPlainText(),'还没发出的草稿')
            self.assertEqual(len(w.pages),4)
            w.shutdown()

    def test_empty_placeholders_are_not_saved_but_empty_projects_can_be_reopened(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            used=w.add_project(folder);used.log.append_message('user','检查文件')
            unused=w.new_conversation();unused.prompt.setPlainText('  \n ')
            empty_project=w.add_project(str(Path(folder)/'empty'))
            project_key=empty_project.project_key
            w.save()
            data=json.loads(w.path.read_text('utf8'))
            self.assertEqual([p['id'] for p in data['projects'][0]['conversations']],[used.conversation_id])
            self.assertEqual(data['projects'][0]['selected'],used.conversation_id)
            self.assertEqual(data['projects'][1]['conversations'],[])
            self.assertIsNone(data['selected'])
            self.assertEqual(data['selected_project'],project_key)
            w.shutdown()
            self.assertNotIn(unused.conversation_id,w.pages)
            restored=Workspaces(lambda:'config',folder)
            self.assertTrue(restored.storage_ok)
            self.assertEqual(len(restored.pages),1)
            self.assertEqual(restored.selected_project_key,project_key)
            self.assertIs(restored.stack.currentWidget(),restored.empty)
            self.assertFalse(restored.project_items[project_key].isHidden())
            with patch.object(restored,'choose_project') as choose:
                restored.new_button.click()
                choose.assert_not_called()
            current=restored.stack.currentWidget()
            self.assertEqual(current.project_key,project_key)
            restored.shutdown()
            self.assertEqual(json.loads(restored.path.read_text('utf8'))['projects'][1]['conversations'],[])

    def test_legacy_empty_conversations_are_removed_without_losing_drafts_or_history(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            path=Path(folder)/'work-projects.json'
            path.write_text(json.dumps({'version':2,'selected':'empty2','projects':[{
                'folder':folder,'selected':'empty2','conversations':[
                    {'id':'history','messages':[{'role':'user','content':'已有消息'}]},
                    {'id':'empty1','title':'新对话','draft':'','log':''},
                    {'id':'draft','draft':'尚未发送的想法'},
                    {'id':'empty2','title':'新对话','state':'准备就绪'}]}]}),encoding='utf8')
            w=Workspaces(lambda:'config',folder)
            self.assertEqual(set(w.pages),{'history','draft'})
            self.assertEqual(w.selected_id,'draft')
            self.assertEqual(w.pages['draft'].prompt.toPlainText(),'尚未发送的想法')
            self.assertIn('已有消息',w.pages['history'].log.toPlainText())
            w.shutdown()
            data=json.loads(path.read_text('utf8'))
            self.assertEqual([p['id'] for p in data['projects'][0]['conversations']],['history','draft'])

    def test_started_task_is_never_treated_as_an_unused_placeholder(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            running=w.add_project(folder);running.prompt.setPlainText('检查项目');running.start()
            running.prompt.clear();running.log.clear();running.pending_task=None
            empty=w.new_conversation()
            w.discard_unused()
            self.assertNotIn(empty.conversation_id,w.pages)
            self.assertIs(w.stack.currentWidget(),running)
            self.assertTrue(running.is_running)
            self.assertFalse(running.client.closed)
            running.client.cancel()
            w.shutdown()
            restored=Workspaces(lambda:'config',folder)
            self.assertIn(running.conversation_id,restored.pages)
            self.assertFalse(restored.is_unused(restored.pages[running.conversation_id]))
            restored.shutdown()

    def test_closing_chat_discards_only_unused_work_conversations(self):
        from types import SimpleNamespace
        from PySide6.QtCore import QSettings
        from deskpet.chat.window import ChatWindow
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient),\
                patch('deskpet.chat.companion_runtime.CompanionRuntime'):
            root=Path(folder)
            pet=SimpleNamespace(panel=SimpleNamespace(data_dir=root,
                settings=QSettings(str(root/'settings.ini'),QSettings.IniFormat)),
                variant='refined',character_pack=None,character_name='洛天依')
            window=ChatWindow(pet)
            workspace=window.work_panel
            draft=workspace.add_project(folder);draft.prompt.setPlainText('稍后继续写')
            blank=workspace.new_conversation()
            window.show();self.app.processEvents();window.close()
            self.assertNotIn(blank.conversation_id,workspace.pages)
            self.assertIs(workspace.stack.currentWidget(),draft)
            self.assertEqual(draft.prompt.toPlainText(),'稍后继续写')
            data=json.loads(workspace.path.read_text('utf8'))
            self.assertEqual(len(data['projects'][0]['conversations']),1)
            window.shutdown()

    def test_legacy_history_is_migrated_with_one_exact_backup(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            path=Path(folder)/'work-projects.json'
            original=json.dumps({'version':1,'selected':os.path.normcase(str(Path(folder).resolve())),
                'projects':[{'folder':folder,'session_id':'legacy123','draft':'接着做',
                    'messages':[{'role':'user','content':'旧项目的任务'}],'log':'旧记录',
                    'continue_session':True,'auto_approve':True}]}).encode()
            path.write_bytes(original)
            w=Workspaces(lambda:'config',folder);w.save()
            backup=path.with_suffix('.v1.backup.json')
            self.assertEqual(backup.read_bytes(),original)
            p=w.stack.currentWidget()
            self.assertEqual(p.client.session_id,'legacy123')
            self.assertIn('旧项目的任务',p.log.toPlainText())
            self.assertTrue(p.auto_approve.isChecked())
            self.assertEqual(json.loads(path.read_text('utf8'))['version'],2)
            w.shutdown()
            w=Workspaces(lambda:'config',folder);w.shutdown()
            self.assertEqual(backup.read_bytes(),original)

    def test_switching_sibling_conversations_does_not_lose_pending_approval(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            first=w.add_project(folder);first.prompt.setPlainText('检查文件');first.start()
            first.client.approval.emit({'id':'approval1','arguments':{'command':'Get-Content a.txt'}})
            second=w.new_conversation();second.prompt.setPlainText('另一个任务');second.start()
            self.assertEqual(second.client.starts,[])
            self.assertEqual(first.approval_id,'approval1')
            w.show_running()
            self.assertIs(w.stack.currentWidget(),first)
            first.answer(False)
            self.assertEqual(first.client.answers,[('approval1',False)])
            self.assertEqual(second.client.answers,[])
            w.shutdown()
    def test_bad_record_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            p=Path(folder)/'work-projects.json';p.write_text('broken','utf8')
            w=Workspaces(lambda:'config',folder);w.save();w.shutdown()
            self.assertEqual(p.read_text('utf8'),'broken')

    def test_sidebar_collapses_on_narrow_window_and_remembers_manual_choice(self):
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            w.add_project(folder)
            w.resize(960,700);w.show();self.app.processEvents()
            self.assertTrue(w.sidebar.isVisible())
            self.assertTrue(w.new_button.isVisible())
            self.assertFalse(w.new_compact.isVisible())
            w.resize(590,600);self.app.processEvents()
            self.assertFalse(w.sidebar.isVisible())
            self.assertTrue(w.sidebar_button.isVisible())
            self.assertFalse(w.new_button.isVisible())
            self.assertTrue(w.new_compact.isVisible())
            w.resize(960,700);self.app.processEvents()
            self.assertTrue(w.sidebar.isVisible())
            self.assertFalse(w.new_compact.isVisible())
            w.toggle_sidebar()
            self.assertTrue(w.new_compact.isVisible())
            w.shutdown();w.close()
            restored=Workspaces(lambda:'config',folder)
            restored.resize(960,700);restored.show();self.app.processEvents()
            self.assertFalse(restored.sidebar.isVisible())
            restored.shutdown();restored.close()

    def test_open_switch_and_restore_conversations_show_latest_message(self):
        from PySide6.QtWidgets import QTabWidget, QWidget
        from PySide6.QtTest import QTest
        with tempfile.TemporaryDirectory() as folder,patch('deskpet.chat.work_client.WorkClient',FakeClient):
            w=Workspaces(lambda:'config',folder)
            first=w.add_project(folder)
            first.log.set_messages([{'role':'assistant','content':f'工作结果 {i}\n' + '详细说明 ' * 30}
                                    for i in range(35)])
            second=w.new_conversation()
            # Older records may contain only a plain-text transcript.
            second.log.setPlainText('\n'.join(f'旧版记录 {i}' for i in range(100)))
            w.select_conversation(first.conversation_id)
            w.shutdown()

            tabs=QTabWidget();tabs.resize(960,700)
            tabs.addTab(QWidget(),'陪伴')
            restored=Workspaces(lambda:'config',folder)
            tabs.addTab(restored,'工作');tabs.show()
            self.addCleanup(tabs.close)
            self.addCleanup(restored.shutdown)
            QTest.qWait(30)
            tabs.setCurrentIndex(1);QTest.qWait(30)

            def assert_latest(page):
                bar=page.log.verticalScrollBar()
                self.assertGreater(bar.maximum(),0)
                self.assertEqual(bar.value(),bar.maximum())

            current=restored.stack.currentWidget()
            assert_latest(current)
            # Showing once must not keep pulling the reader back down.
            current.log.verticalScrollBar().setValue(0)
            restored.refresh_status();QTest.qWait(30)
            self.assertEqual(current.log.verticalScrollBar().value(),0)
            tabs.setCurrentIndex(0);tabs.setCurrentIndex(1);QTest.qWait(30)
            assert_latest(current)
            other=list(restored.pages.values())[1]
            restored.select_conversation(other.conversation_id);QTest.qWait(30)
            assert_latest(other)
            restored.select_conversation(current.conversation_id);QTest.qWait(30)
            assert_latest(current)
            tabs.hide();tabs.show();QTest.qWait(30)
            assert_latest(current)
            restored.shutdown();tabs.close()
