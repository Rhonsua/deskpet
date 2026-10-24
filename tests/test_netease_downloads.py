"""Synthetic local HTTP/WAV fixtures only, no account, CDN or real music."""
import io
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
from PySide6.QtCore import QCoreApplication
from netease_music.downloads import Downloader,export_lrc,safe_stem,MAX_BYTES

def fixture():
    data=io.BytesIO()
    with wave.open(data,'wb') as wav:wav.setparams((1,2,8000,0,'NONE',''));wav.writeframes(b'\x00\x00'*800)
    return data.getvalue()
AUDIO=fixture()
class Handler(BaseHTTPRequestHandler):
    cookies=[]
    def log_message(self,*_):pass
    def do_GET(self):
        self.cookies.append(self.headers.get('Cookie'))
        if self.path=='/redirect':
            self.send_response(302);self.send_header('Location','https://example.test/stolen');self.end_headers();return
        if self.path=='/error':self.send_error(403);return
        body=b'<html>not audio</html>' if self.path in ('/html','/fake-audio') else AUDIO
        self.send_response(200)
        self.send_header('Content-Type','text/html' if self.path=='/html' else 'audio/wav')
        length=MAX_BYTES+1 if self.path=='/huge' else len(body)+100 if self.path=='/truncated' else len(body)
        self.send_header('Content-Length',str(length));self.send_header('Set-Cookie','untrusted=must-not-replay');self.end_headers()
        if self.path=='/slow':time.sleep(.3)
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        self.close_connection=True
class DownloadsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QCoreApplication.instance() or QCoreApplication([])
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.directory=Path(self.temp.name)
        self.downloader=Downloader();self.done=[];self.failed=[];self.warnings=[];self.skipped=[]
        self.downloader.skipped.connect(lambda:self.skipped.append(True))
        self.downloader.completed.connect(lambda *args:self.done.append(args));self.downloader.failed.connect(self.failed.append);self.downloader.warning.connect(self.warnings.append)
        self.patch=patch('netease_music.downloads.validate_media_url',side_effect=lambda value:value);self.patch.start()
    def tearDown(self):self.downloader.cancel();self.patch.stop();self.temp.cleanup()
    def start(self,path,**kwargs):self.downloader.start(f'http://127.0.0.1:{self.server.server_port}'+path,self.directory,'test','mp3',**kwargs)
    def wait(self):
        deadline=time.monotonic()+4
        while not self.done and not self.failed and not self.skipped and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertTrue(self.done or self.failed or self.skipped,'request did not terminate')
    def test_audio_lrc_actual_format_unique_and_no_cookie(self):
        (self.directory/'test.wav').write_bytes(b'existing')
        self.start('/audio',lrc='[00:00.00]合成测试',expected_size=len(AUDIO));self.wait()
        self.assertFalse(self.failed);audio,lrc=map(Path,self.done[0])
        self.assertEqual(audio.name,'test (1).wav');self.assertEqual(audio.read_bytes(),AUDIO)
        self.assertEqual(lrc.stem,audio.stem);self.assertEqual(lrc.read_text(encoding='utf-8'),'[00:00.00]合成测试')
        self.assertEqual((self.directory/'test.wav').read_bytes(),b'existing');self.assertFalse(any(self.directory.glob('*.part')))
        self.assertFalse(any(Handler.cookies))
    def test_rejected_content_redirect_and_limits(self):
        for path in ('/html','/fake-audio','/redirect','/error','/huge','/truncated'):
            with self.subTest(path=path):
                self.failed.clear();self.done.clear();self.start(path);self.wait();self.assertTrue(self.failed);self.assertFalse(self.done);self.assertEqual(list(self.directory.iterdir()),[])
    def test_cancel_ignores_late_reply(self):
        self.start('/slow');self.downloader.cancel()
        end=time.monotonic()+.5
        while time.monotonic()<end:self.app.processEvents();time.sleep(.005)
        self.assertFalse(self.done);self.assertFalse(self.failed);self.assertEqual(list(self.directory.iterdir()),[])
    def test_idle_timeout_cleans_partial(self):
        self.start('/slow');self.downloader.timer.start(20);self.wait()
        self.assertTrue(self.failed);self.assertEqual(list(self.directory.iterdir()),[])
    def test_no_lyrics_does_not_create_sidecar(self):
        self.start('/audio');self.wait();self.assertTrue(self.done)
        self.assertEqual(self.done[0][1],'');self.assertEqual(list(self.directory.glob('*.lrc')),[])
    def test_expected_size_mismatch(self):
        self.start('/audio',expected_size=10);self.wait();self.assertTrue(self.failed);self.assertFalse(self.done)
    def test_existing_lyric_reserves_the_entire_pair(self):
        (self.directory/'test.lrc').write_text('old',encoding='utf-8');self.start('/audio',lrc='new');self.wait()
        self.assertTrue(self.done);self.assertFalse(self.warnings)
        audio,lrc=map(Path,self.done[0]);self.assertEqual(audio.name,'test (1).wav');self.assertEqual(lrc.stem,audio.stem)
        self.assertEqual(lrc.read_text(),'new');self.assertEqual((self.directory/'test.lrc').read_text(),'old')
    def test_lyric_write_failure_keeps_audio(self):
        with patch('netease_music.downloads.export_lrc',side_effect=OSError('disk full')):
            self.start('/audio',lrc='new');self.wait()
        self.assertTrue(self.done);self.assertTrue(self.warnings);self.assertEqual(self.done[0][1],'')
        self.assertTrue(Path(self.done[0][0]).is_file())
    def test_names_and_lyrics_only(self):
        self.assertEqual(safe_stem('CON'),'_CON');self.assertNotIn('/',safe_stem('../a?'))
        path=Path(export_lrc(self.directory,'LPT1','[00:00]synthetic'));self.assertEqual(path.name,'_LPT1.lrc')
        other=Path(export_lrc(self.directory,'LPT1','second'));self.assertNotEqual(path,other)
        with self.assertRaises(ValueError):export_lrc(self.directory,'empty','')
    def test_confirm_overwrite_uses_actual_format_and_matching_lrc(self):
        audio=self.directory/'test.wav';lrc=self.directory/'test.lrc'
        audio.write_bytes(b'old audio');lrc.write_text('old lyrics')
        asked=[]
        def confirm(paths):
            asked.extend(paths)
            self.assertEqual(audio.read_bytes(),b'old audio')
            self.assertEqual(lrc.read_text(),'old lyrics')
            return 'overwrite'
        self.downloader.resolve_conflict=confirm
        self.start('/audio',lrc='new lyrics');self.wait()
        self.assertEqual(asked,[audio,lrc]);self.assertEqual(self.done,[(str(audio),str(lrc))])
        self.assertEqual(audio.read_bytes(),AUDIO);self.assertEqual(lrc.read_text(),'new lyrics')
        self.assertEqual(set(self.directory.iterdir()),{audio,lrc})
    def test_skip_preserves_both_files_and_cleans_partial(self):
        audio=self.directory/'test.wav';lrc=self.directory/'test.lrc'
        audio.write_bytes(b'old');lrc.write_text('old')
        self.downloader.resolve_conflict=lambda paths:'skip'
        self.start('/audio',lrc='new');self.wait()
        self.assertTrue(self.skipped);self.assertFalse(self.done or self.failed)
        self.assertEqual(audio.read_bytes(),b'old');self.assertEqual(lrc.read_text(),'old')
        self.assertEqual(set(self.directory.iterdir()),{audio,lrc})
    def test_lrc_only_collision_can_replace_pair(self):
        lrc=self.directory/'test.lrc';lrc.write_text('old')
        self.downloader.resolve_conflict=lambda paths:'overwrite'
        self.start('/audio',lrc='new');self.wait()
        self.assertEqual(Path(self.done[0][0]).name,'test.wav')
        self.assertEqual(lrc.read_text(),'new')
    def test_bad_download_never_prompts_or_overwrites(self):
        audio=self.directory/'test.wav';audio.write_bytes(b'old')
        asked=[]
        self.downloader.resolve_conflict=lambda paths:asked.append(paths) or 'overwrite'
        self.start('/fake-audio');self.wait()
        self.assertTrue(self.failed);self.assertFalse(asked)
        self.assertEqual(audio.read_bytes(),b'old')
    def test_cancellation_inside_prompt_does_not_commit(self):
        audio=self.directory/'test.wav';audio.write_bytes(b'old')
        asked=[]
        def confirm(paths):
            asked.append(paths);self.downloader.cancel();return 'overwrite'
        self.downloader.resolve_conflict=confirm
        self.start('/audio')
        deadline=time.monotonic()+4
        while not asked and time.monotonic()<deadline:self.app.processEvents();time.sleep(.005)
        self.assertTrue(asked);self.assertFalse(self.done or self.failed or self.skipped)
        self.assertEqual(audio.read_bytes(),b'old');self.assertEqual(list(self.directory.iterdir()),[audio])
    def test_failed_atomic_replace_preserves_old_audio(self):
        audio=self.directory/'test.wav';audio.write_bytes(b'old')
        self.downloader.resolve_conflict=lambda paths:'overwrite'
        with patch('netease_music.downloads.os.replace',side_effect=PermissionError('in use')):
            self.start('/audio');self.wait()
        self.assertTrue(self.failed);self.assertEqual(audio.read_bytes(),b'old')
        self.assertEqual(list(self.directory.iterdir()),[audio])
    def test_lyrics_only_explicit_overwrite(self):
        path=Path(export_lrc(self.directory,'test','old'))
        self.assertEqual(Path(export_lrc(self.directory,'test','new',overwrite=True)),path)
        self.assertEqual(path.read_text(),'new');self.assertEqual(list(self.directory.iterdir()),[path])
if __name__=='__main__':unittest.main()
