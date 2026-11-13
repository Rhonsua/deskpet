"""Worker lifecycle failures must never manufacture a resumable session."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from deskpet.chat import harness_worker


class WorkerLifecycleTests(unittest.TestCase):
    def run_worker(self, folder, resumed=False, prompt_failure=False):
        root = Path(folder)
        home = root / 'home'
        home.mkdir(exist_ok=True)
        payload = dict(api_key='dummy-secret', workspace=str(root), home=str(home),
                       base_url='http://localhost', model='fake', session_id='test123',
                       prompt='task', resume=resumed)
        client = Mock()
        if not prompt_failure:
            client.request.side_effect = TimeoutError('initialize timed out dummy-secret')
        client.next_request.side_effect = EOFError()
        session = Mock()
        session.side_effect = RuntimeError('prompt rejected before receipt')
        modules = {
            'deepseek_harness':SimpleNamespace(HarnessClient=Mock(return_value=client), HarnessConfig=lambda **kw: kw),
            'deepseek_harness.models':SimpleNamespace(InitializeResponse=object),
        }
        with patch.dict('sys.modules', modules), patch.object(harness_worker.sys, 'stdin', io.StringIO(json.dumps(payload)+'\n')), \
             patch('deskpet.chat.harness_bootstrap.ensure_runtime', return_value=root/'dsh.cmd'), \
             patch.object(harness_worker.threading, 'Thread'), \
             patch.object(harness_worker, 'run_conversation', session), \
             patch('deskpet.chat.harness_runtime.runtime_launch_args', return_value=('node','bin.js')), \
             patch('deskpet.chat.work_permissions.write_runtime_patch', return_value=home/'privacy.patch.yml'), \
             patch.object(harness_worker, 'emit') as emit:
            harness_worker.main()
        return home, session, emit

    def test_initialize_timeout_does_not_submit_task_or_create_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            home, session, emit = self.run_worker(folder)
            session.assert_not_called()
            self.assertFalse((home/'session-ready').exists())
            failed = [c.kwargs for c in emit.call_args_list if c.args == ('failed',)]
            self.assertIn('输入已保留', failed[-1]['text'])
            self.assertNotIn('dummy-secret', failed[-1]['text'])

    def test_failed_resume_initialization_preserves_old_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)/'home';home.mkdir()
            marker=home/'session-ready';marker.write_text('test123')
            _, session, _ = self.run_worker(folder, resumed=True)
            session.assert_not_called()
            self.assertEqual(marker.read_text(),'test123')

    def test_initialize_alone_does_not_make_session_resumable(self):
        with tempfile.TemporaryDirectory() as folder:
            home, session, emit = self.run_worker(folder, prompt_failure=True)
            session.assert_called_once()
            self.assertFalse((home/'session-ready').exists())
            self.assertFalse(any(c.kwargs.get('event',{}).get('type')=='session_ready' for c in emit.call_args_list))
