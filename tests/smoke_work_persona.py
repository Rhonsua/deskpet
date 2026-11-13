"""Verify the real DSH backend loads project persona text using a local fake API."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.tianyi_work_persona.instructions import apply_persona, remove_persona


def main():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            events = [
                ('message_start', {'type': 'message_start', 'message': {
                    'id': 'local-test', 'type': 'message', 'role': 'assistant',
                    'model': 'deepseek-flash', 'content': [], 'usage': {'input_tokens': 1, 'output_tokens': 0}}}),
                ('content_block_start', {'type': 'content_block_start', 'index': 0,
                                         'content_block': {'type': 'text', 'text': ''}}),
                ('content_block_delta', {'type': 'content_block_delta', 'index': 0,
                                         'delta': {'type': 'text_delta', 'text': 'LOCAL_PERSONA_OK'}}),
                ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'},
                                   'usage': {'output_tokens': 4}}),
                ('message_stop', {'type': 'message_stop'}),
            ]
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for kind, value in events:
                self.wfile.write(('event: ' + kind + '\ndata: ' + json.dumps(value) + '\n\n').encode())

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scratch = ROOT / 'local-work/mod-checks'
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='work-persona-', dir=scratch) as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            (project / '.git').mkdir()
            original = b'# PROJECT_RULES_UNCHANGED\n'
            (project / 'AGENTS.md').write_bytes(original)
            persona = (ROOT / 'extensions/tianyi_work_persona/persona.md').read_text('utf-8')
            apply_persona(project, persona)
            for enabled in (True, False):
                if not enabled:
                    remove_persona(project)
                process = subprocess.Popen(
                    [str(ROOT / '.harness-venv/Scripts/python.exe'), '-u', '-m', 'deskpet.chat.harness_worker'],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    env=dict(os.environ, PYTHONIOENCODING='utf-8'))
                try:
                    session = uuid.uuid4().hex
                    payload = dict(workspace=str(project), home=str(root / session),
                        session_id=session, prompt='Describe how you will help with this project.',
                        model='deepseek-flash', api_key='local-fake-key',
                        base_url=f'http://127.0.0.1:{server.server_port}/v1', resume=False)
                    inbox = queue.Queue()
                    def read_events():
                        for line in process.stdout:
                            inbox.put(json.loads(line))
                        inbox.put(None)
                    reader = threading.Thread(target=read_events, daemon=True)
                    reader.start()
                    process.stdin.write(json.dumps(payload) + '\n')
                    process.stdin.flush()
                    deadline = time.monotonic() + 120
                    while True:
                        event = inbox.get(timeout=max(0.1, deadline - time.monotonic()))
                        assert event is not None, 'worker ended before completing the test'
                        if event['type'] in ('failed', 'completed'):
                            assert event['type'] == 'completed', event
                            assert event['text'] == 'LOCAL_PERSONA_OK', event
                            break
                    process.wait(timeout=10)
                    reader.join(timeout=3)
                    sent = json.dumps(requests[-1], ensure_ascii=False)
                    assert ('洛天依 · 工作伙伴' in sent) == enabled
                    assert 'PROJECT_RULES_UNCHANGED' in sent
                    assert (project / 'AGENTS.md').read_bytes() == original
                    print('PASS official backend persona', 'import' if enabled else 'removal', flush=True)
                finally:
                    if process.poll() is None:
                        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                                       capture_output=True, timeout=10)
                        process.wait(timeout=5)
                    process.stdin.close()
                    process.stdout.close()
            assert len(requests) == 2
            print('PASS 2 local fake API requests, 0 paid API requests', flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    main()
