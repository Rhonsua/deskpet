"""A few KB are enough to exercise pause, resume and integrity checking."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packaging/voice_setup'))
from download import fetch_archive


class HelperDownloadTests(unittest.TestCase):
    def setUp(self):
        self.data = bytes(range(251)) * 21
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.sent = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                start, end = map(int, self.headers['Range'][6:].split('-'))
                outer.sent.append(start)
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(outer.data)}')
                self.end_headers()
                self.wfile.write(outer.data[start:end + 1])

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name)

    def fetch(self, progress=lambda *_: None, checksum=None, cancel=None):
        return fetch_archive(self.directory, progress, cancel=cancel, size=len(self.data),
                             checksum=checksum or self.sha, chunk_size=128, name='test.7z',
                             sources=[f'http://127.0.0.1:{self.server.server_port}/file'])

    def test_resume_and_reuse(self):
        stop = threading.Event()
        with self.assertRaises(InterruptedError):
            self.fetch(lambda n, _: stop.set() if n else None, cancel=stop)
        before = list(self.sent)
        self.assertTrue(before)
        cached = json.loads((self.directory/'test.7z.parts.json').read_text())['done']
        self.assertEqual(set(before), {i*128 for i in cached})
        self.sent.clear()
        self.assertEqual(self.fetch().read_bytes(), self.data)
        self.assertFalse(set(before) & set(self.sent))
        self.sent.clear()
        self.fetch()
        self.assertFalse(self.sent)

    def test_corrupt_archive_never_activated(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.fetch(checksum='0' * 64)
        self.assertFalse((self.directory/'test.7z').exists())
        self.assertFalse((self.directory/'test.7z.parts.json').exists())
