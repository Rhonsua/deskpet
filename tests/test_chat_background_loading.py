"""Small local fixtures for image loading and unchanged workspace autosaves."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from deskpet.chat.sticker_picker import StickerPicker
from deskpet.chat import sticker_thumbnails
from deskpet.chat.workspaces import Workspaces, DeferredConversation
from tests.test_work_panel import FakeClient


class BackgroundLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_thumbnail_cache_is_bounded_and_invalidates_changed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'small.png'
            image = QImage(128, 96, QImage.Format_RGB32)
            image.fill(Qt.red)
            self.assertTrue(image.save(str(path)))
            sticker_thumbnails._decode.cache_clear()
            first = sticker_thumbnails.read_thumbnail(path)
            self.assertEqual((first.width(), first.height()), (64, 48))
            sticker_thumbnails.read_thumbnail(path)
            self.assertEqual(sticker_thumbnails._decode.cache_info().misses, 1)
            image.fill(Qt.blue)
            self.assertTrue(image.save(str(path)))
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
            second = sticker_thumbnails.read_thumbnail(path)
            self.assertNotEqual(first.pixel(0, 0), second.pixel(0, 0))
            self.assertEqual(sticker_thumbnails._decode.cache_info().misses, 2)
            self.assertEqual(sticker_thumbnails._decode.cache_info().maxsize, 256)

    def test_picker_decodes_off_gui_thread_and_rejects_stale_results(self):
        entry = SimpleNamespace(id='one', path=Path('unused'), title='one',
                                animated=False, character='洛天依')
        catalog = SimpleNamespace(panel_state=lambda: dict(recent=['one'], favorites=[]),
                                  get=lambda key: entry, items={'one':entry}, custom={})
        gui_thread = threading.get_ident()
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        threads = []
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.red)

        def decode(path):
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            returned.set()
            return image

        with patch.object(sticker_thumbnails, 'read_thumbnail', side_effect=decode):
            picker = StickerPicker(catalog, lambda: None)
            try:
                self.assertEqual(threads, [])  # Hidden construction does no decode.
                picker.show()
                for _ in range(100):
                    QTest.qWait(10)
                    if started.is_set():
                        break
                self.assertTrue(started.is_set())
                self.assertNotEqual(threads[0], gui_thread)
                old_generation = picker._thumbnail_generation
                # The GUI still processes a query while the decoder is blocked.
                picker.query.setText('absent')
                self.assertEqual(picker.list.count(), 0)
                release.set()
                picker._thumbnail_ready(old_generation, 'one', image)
                self.assertEqual(picker.list.count(), 0)
                for _ in range(100):
                    QTest.qWait(10)
                    if not picker._thumbnail_jobs:
                        break
                self.assertTrue(returned.is_set())
                self.assertEqual(picker._thumbnail_jobs, {})
            finally:
                release.set()
                picker.close()

    def test_unchanged_autosave_does_not_copy_or_encode_history_and_edits_persist(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('deskpet.chat.work_client.WorkClient', FakeClient):
            workspaces = Workspaces(lambda: 'config', folder)
            try:
                page = workspaces.add_project(folder)
                page.log.append_message('assistant', 'small history')
                workspaces.save()
                with patch.object(page.log, 'toPlainText', wraps=page.log.toPlainText) as text, \
                        patch('deskpet.chat.workspaces.json.dumps', wraps=json.dumps) as encode:
                    for _ in range(5):
                        workspaces.save()
                    text.assert_not_called()
                    encode.assert_not_called()
                page.prompt.setPlainText('changed draft')
                page.events.setPlainText('changed event')
                page.restore_auto_approve(True)
                page.state.setText('changed state')
                workspaces.save()
                saved = json.loads(workspaces.path.read_text('utf8'))['projects'][0]['conversations'][0]
                self.assertEqual(saved['draft'], 'changed draft')
                self.assertEqual(saved['events'], 'changed event')
                self.assertEqual(saved['state'], 'changed state')
                self.assertTrue(saved['auto_approve'])
                page.pending_inputs[1] = 'unconfirmed input'
                page.prompt.clear()
                workspaces.save()
                saved = json.loads(workspaces.path.read_text('utf8'))['projects'][0]['conversations'][0]
                self.assertEqual(saved['draft'], 'unconfirmed input')
            finally:
                workspaces.shutdown()

    def test_failed_autosave_retries_without_another_edit(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('deskpet.chat.work_client.WorkClient', FakeClient):
            workspaces = Workspaces(lambda: 'config', folder)
            try:
                page = workspaces.add_project(folder)
                page.prompt.setPlainText('preserve draft')
                with patch.object(workspaces, 'write_record', side_effect=OSError('test failure')) as write:
                    workspaces.save()
                    workspaces.save()
                    self.assertEqual(write.call_count, 2)
                workspaces.save()
                self.assertTrue(workspaces.path.is_file())
            finally:
                workspaces.shutdown()

    def test_restore_builds_only_selected_panel_and_preserves_unopened_data(self):
        from deskpet.chat.work_panel import WorkPanel
        with tempfile.TemporaryDirectory() as folder, \
                patch('deskpet.chat.work_client.WorkClient', FakeClient):
            conversations = [dict(id='thread'+str(i), title='saved '+str(i), used=True,
                                  draft='draft '+str(i), log='history '+str(i),
                                  events='event '+str(i), session_id='session'+str(i),
                                  auto_approve=i%2 == 0, continue_session=True,
                                  messages=[dict(role='user', content='message '+str(i))])
                             for i in range(4)]
            path = Path(folder) / 'work-projects.json'
            path.write_text(json.dumps(dict(version=2, selected='thread2', projects=[
                dict(folder=folder, selected='thread2', conversations=conversations)])), 'utf8')
            with patch('deskpet.chat.workspaces.WorkPanel', wraps=WorkPanel) as construct:
                workspaces = Workspaces(lambda: 'config', folder)
                try:
                    self.assertEqual(construct.call_count, 1)
                    self.assertEqual(list(workspaces.pages), [r['id'] for r in conversations])
                    self.assertIsInstance(workspaces.pages['thread0'], DeferredConversation)
                    selected = workspaces.stack.currentWidget()
                    self.assertEqual(selected.conversation_id, 'thread2')
                    self.assertTrue(selected.continue_session.isChecked())
                    self.assertTrue(selected.auto_approve.isChecked())
                    # Background status, filtering, persistence and pruning must
                    # not instantiate the unopened conversations.
                    workspaces.filter_tree('saved')
                    workspaces.refresh_status()
                    workspaces.discard_unused()
                    workspaces.save()
                    self.assertEqual(construct.call_count, 1)
                    saved = json.loads(path.read_text('utf8'))['projects'][0]['conversations']
                    for index in (0, 1, 3):
                        self.assertEqual(saved[index], conversations[index])
                    workspaces.select_conversation('thread0')
                    self.assertEqual(construct.call_count, 2)
                    opened = workspaces.stack.currentWidget()
                    self.assertEqual(opened.prompt.toPlainText(), 'draft 0')
                    self.assertEqual(opened.client.session_id, 'session0')
                    self.assertIn('message 0', opened.log.toPlainText())
                    self.assertTrue(opened.auto_approve.isChecked())
                    self.assertEqual(list(workspaces.pages), [r['id'] for r in conversations])
                    # Compatibility access can load history without changing
                    # the user's selected conversation.
                    self.assertIn('message 1', workspaces.pages['thread1'].log.toPlainText())
                    self.assertEqual(construct.call_count, 3)
                    self.assertEqual(workspaces.selected_id, 'thread0')
                    self.assertIs(workspaces.stack.currentWidget(), opened)
                finally:
                    workspaces.shutdown()
                self.assertEqual(construct.call_count, 3)

    def test_opening_deferred_sibling_preserves_live_approval_and_draft(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('deskpet.chat.work_client.WorkClient', FakeClient):
            path = Path(folder) / 'work-projects.json'
            path.write_text(json.dumps(dict(version=2, selected='active', projects=[
                dict(folder=folder, selected='active', conversations=[
                    dict(id='active', draft='new task'),
                    dict(id='other', draft='preserved sibling', session_id='previous')])])), 'utf8')
            workspaces = Workspaces(lambda: 'config', folder)
            try:
                active = workspaces.stack.currentWidget()
                active.start()
                active.request_approval(dict(id='approval1', toolName='read', arguments=dict(path='file')))
                self.assertEqual(active.approval_id, 'approval1')
                workspaces.select_conversation('other')
                self.assertTrue(active.is_running)
                self.assertEqual(active.approval_id, 'approval1')
                self.assertEqual(workspaces.stack.currentWidget().prompt.toPlainText(), 'preserved sibling')
                workspaces.show_running()
                self.assertIs(workspaces.stack.currentWidget(), active)
                self.assertEqual(workspaces.approval_id, 'approval1')
            finally:
                workspaces.shutdown()


if __name__ == '__main__':
    unittest.main()
