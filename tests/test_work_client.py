import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from deskpet.chat.work_client import WorkClient, harness_endpoint
from deskpet.chat.harness_worker import redact

class WorkTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.app=QApplication.instance() or QApplication([])
 def test_official_endpoint_normalization(self):
  for path in ('','/v1','/v1/chat/completions','/anthropic','/anthropic/v1/messages'):
   self.assertEqual(harness_endpoint('https://api.deepseek.com'+path),'https://api.deepseek.com/anthropic')
  with self.assertRaises(ValueError): harness_endpoint('https://example.com/v1')
 def test_stale_process_ignored(self):
  client=WorkClient(); old=Mock(); current=Mock()
  client.process=current; client.busy=True
  client._finished(old);client._error(old);client._read(old)
  self.assertTrue(client.busy);self.assertIs(client.process,current)
 def test_invalid_protocol_and_late_completion(self):
  client=WorkClient(); process=Mock();client.process=process;client.busy=True
  client._cancelled=True
  process.readAllStandardOutput.return_value=b'[]\n{"type":"event","event":[]}\n{"type":"completed","text":"late"}\n'
  completed=Mock();failed=Mock();client.completed.connect(completed);client.failed.connect(failed)
  client._read(process)
  completed.assert_not_called();failed.assert_called_once()
 def test_redaction(self):
  self.assertEqual(redact({'authorization':'secret','nested':'http://localhost/?token=secret'})['authorization'],'[已隐藏]')
  self.assertNotIn('=secret',redact('http://localhost/?token=secret'))
 def test_only_confirmed_candidate_replaces_previous_session(self):
  client=WorkClient();process=Mock();client.process=process;client.busy=True
  client.session_id='previous';client._pending_session_id='candidate'
  process.readAllStandardOutput.return_value=b'{"type":"event","event":{"type":"started","session_id":"candidate"}}\n'
  client._read(process);self.assertEqual(client.session_id,'previous')
  process.readAllStandardOutput.return_value=b'{"type":"event","event":{"type":"session_ready","session_id":"wrong"}}\n'
  client._read(process);self.assertEqual(client.session_id,'previous')
  process.readAllStandardOutput.return_value=b'{"type":"event","event":{"type":"session_ready","session_id":"candidate"}}\n'
  client._read(process);self.assertEqual(client.session_id,'candidate')

 def test_runtime_launch_bypasses_batch_and_preserves_paths(self):
  from deskpet.chat.harness_runtime import runtime_launch_args
  with tempfile.TemporaryDirectory(prefix='启动 路径 ') as folder:
   root=Path(folder);cli=root/'node_modules/.bin/dsh.cmd'
   entry=root/'node_modules/@deepseek-ai/dsh/lib/bin.js'
   entry.parent.mkdir(parents=True);entry.write_text('test')
   with patch('deskpet.chat.harness_runtime.shutil.which',return_value='C:/Program Files/nodejs/node.exe'):
    args=runtime_launch_args(cli,root/'privacy.patch.yml')
   self.assertEqual(args,('C:/Program Files/nodejs/node.exe',str(entry),'--profile','sdk','--patch',str(root/'privacy.patch.yml')))
 def test_real_failed_start_recovers_busy(self):
  from deskpet.chat.config import ProviderConfig
  client=WorkClient()
  failed=Mock();client.failed.connect(failed)
  with tempfile.TemporaryDirectory() as folder:
   invalid=Path(folder)/'invalid.exe';invalid.write_text('not an executable')
   with patch('deskpet.chat.work_client.PYTHON',invalid):
    client.start(ProviderConfig(base_url='https://api.deepseek.com',model='deepseek-flash'),'test',folder)
    deadline=time.monotonic()+3
    while client.busy and time.monotonic()<deadline:
     self.app.processEvents()
     time.sleep(.01)
  self.assertFalse(client.busy)
  self.assertIsNone(client.process)
  self.assertIsNone(client.session_id)
  failed.assert_called_once()

 def test_runtime_admission_requires_complete_matching_protocol(self):
  from deskpet.chat.harness_runtime import runtime_cli, VERSION
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with self.assertRaises(ValueError):runtime_cli(root)
   (root/'deskpet-runtime-ready.json').write_text(json.dumps({'version':VERSION}))
   package=root/'node_modules/@deepseek-ai/dsh/package.json';package.parent.mkdir(parents=True)
   package.write_text(json.dumps({'version':VERSION}))
   cli=root/'node_modules/.bin/dsh.cmd';cli.parent.mkdir();cli.write_text('test')
   server=root/'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib';server.mkdir(parents=True)
   source=server/'index.js';source.write_text('approvalRequests')
   with self.assertRaises(ValueError):runtime_cli(root)
   source.write_text('approvalRequests allowed-once')
   self.assertEqual(runtime_cli(root),cli)
   package.write_text(json.dumps({'version':'0.2.1rc2'}))
   with self.assertRaises(ValueError):runtime_cli(root)

 def test_frozen_worker_and_sessions_do_not_depend_on_install_root(self):
  from deskpet.chat.work_client import harness_worker_command, session_root
  with tempfile.TemporaryDirectory() as folder:
   data=Path(folder)/'user-data'
   with patch('sys.frozen',True,create=True), patch('deskpet.chat.work_client.QStandardPaths.writableLocation',return_value=str(data)):
    for location in ('C:/Apps/TianyiPet/TianyiPet.exe','D:/Moved/TianyiPet.exe'):
     with patch('sys.executable',location):
      program,args=harness_worker_command()
      self.assertEqual(program,Path(location).with_name('TianyiWorker.exe'))
      self.assertEqual(args,['--harness-worker'])
      self.assertEqual(session_root(),data/'work-sessions')

 def test_frozen_backend_never_falls_back_to_developer_node(self):
  from deskpet.chat.harness_runtime import runtime_launch_args
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);cli=root/'node_modules/.bin/dsh.cmd'
   cli.parent.mkdir(parents=True)
   entry=root/'node_modules/@deepseek-ai/dsh/lib/bin.js'
   entry.parent.mkdir(parents=True);entry.write_text('test')
   with patch('sys.frozen',True,create=True), patch('deskpet.chat.harness_runtime.shutil.which') as lookup:
    with self.assertRaises(ValueError):runtime_launch_args(cli,root/'patch.yml')
    lookup.assert_not_called()
    bundled=cli.parent/'node.exe';bundled.write_bytes(b'test')
    self.assertEqual(runtime_launch_args(cli,root/'patch.yml')[0],str(bundled))

 def test_native_integrity_failure_preserves_existing_binary(self):
  spec=importlib.util.spec_from_file_location('native_setup',Path(__file__).resolve().parents[1]/'packaging/setup_harness_native.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as folder:
   target=Path(folder)/'koffi.node';target.write_bytes(b'existing')
   def fetcher(url):
    if url==module.METADATA:return json.dumps({'version':'3.1.1','dist':{'tarball':module.TARBALL,'integrity':'sha512-bad'}}).encode()
    return b'corrupt'
   with self.assertRaises(ValueError): module.install(target,fetcher)
   self.assertEqual(target.read_bytes(),b'existing')

if __name__=='__main__':unittest.main()
