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
            w.resize(590,600);self.app.processEvents()
            self.assertFalse(w.sidebar.isVisible())
            self.assertTrue(w.sidebar_button.isVisible())
            w.resize(960,700);self.app.processEvents()
            self.assertTrue(w.sidebar.isVisible())
            w.toggle_sidebar();w.shutdown();w.close()
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
