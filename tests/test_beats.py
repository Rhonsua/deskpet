"""Synthetic local fixtures only: no user music or network."""
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from PySide6.QtCore import QCoreApplication
from music_beats import BeatController
from music_beats.core import estimate

class BeatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def test_enabled_default_persistence_and_sample_gate(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            c=BeatController(root);self.assertFalse(c.enabled)
            c.set_source('netease:123');c.set_manual(120)
            self.assertTrue(c.has_timing());self.assertFalse(c.sample(1000,True).available)
            c.set_enabled(True);self.assertTrue(c.sample(1000,False).available)
            restored=BeatController(root);self.assertTrue(restored.enabled)
            c.set_enabled(False);self.assertFalse(c.sample(1000,True).available)
            self.assertFalse(BeatController(root).enabled)
    def test_online_stable_cache_survives_deleted_audio(self):
        import time
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'ephemeral.wav';make_wav(path)
            c=BeatController(root);c.set_enabled(True);c.set_source('netease:123')
            events=[];c.analysisFinished.connect(events.append)
            identity='123|size-123|8000|wav'
            self.assertFalse(c.restore_online('netease:123',identity))
            c.analyze_online(path,identity);self.assertTrue(c.analyzing)
            end=time.monotonic()+10
            while c.analyzing and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
            self.assertEqual(events,[True]);self.assertEqual(c.source,'netease:123');self.assertIsNone(c.path)
            self.assertTrue(c.has_timing());path.unlink()
            restored=BeatController(root);self.assertTrue(restored.restore_online('netease:123',identity))
            self.assertTrue(restored.sample(1000,True).available);self.assertFalse(restored.analyzing)
            self.assertFalse(restored.restore_online('netease:123',identity+'-new-version'));self.assertFalse(restored.has_timing())
            self.assertFalse(restored.restore_online('netease:124',identity));self.assertFalse(restored.has_timing())
    def test_analysis_finished_cancel_and_failure_once(self):
        import time
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'pulse.wav';make_wav(path)
            c=BeatController(root);c.set_source('local:'+str(path.resolve()));events=[];c.analysisFinished.connect(events.append)
            c.analyze();c.cancel();c.cancel();self.assertEqual(events,[False]);self.assertFalse(c.analyzing)
            c.analyze();c.set_enabled(False);self.assertEqual(events,[False,False])
            empty=Path(root)/'broken.wav';empty.write_text('not audio');c.set_source('local:'+str(empty.resolve()));c.analyze()
            end=time.monotonic()+10
            while c.analyzing and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
            self.assertEqual(events,[False,False,False]);self.assertFalse(c.analyzing)
    def test_completed_controller_can_die_before_deferred_process_delete(self):
        import gc
        import time
        import weakref
        from PySide6.QtCore import QEvent
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'pulse.wav';make_wav(path)
            controller=BeatController(root);controller.set_source('netease:123')
            controller.analyze_online(path,'lifetime-fixture')
            end=time.monotonic()+10
            while controller.analyzing and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
            self.assertTrue(controller.has_timing());self.assertFalse(controller.analyzing)
            reference=weakref.ref(controller);del controller;gc.collect()
            # A finished process must not keep its parent alive through Python
            # signal closures while its deferred QObject deletion is queued.
            self.assertIsNone(reference())
            self.app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            self.app.processEvents()
    def test_pulses(self):
        data=estimate([1 if i%50==0 else 0 for i in range(1200)])
        self.assertAlmostEqual(data['bpm'],120)
        self.assertGreater(len(data['beats_ms']),20)
    def test_netease_manual_bpm_has_no_local_audio_analysis(self):
        from music_beats.core import netease_source_id
        self.assertEqual(netease_source_id('netease:123'),'123')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            controller=BeatController(root);controller.set_enabled(True);controller.set_source('netease:123')
            self.assertIsNone(controller.path);self.assertFalse(controller.analysis)
            self.assertIn('首次播放',controller.status)
            controller.set_manual(120,100,1)
            self.assertEqual(controller.sample(600,True).beat_index,1)
            restored=BeatController(root);restored.set_source('netease:123')
            self.assertEqual(restored.sample(600,True),controller.sample(600,True))
            restored.set_source('netease:124');self.assertFalse(restored.sample(600,True).available)
            for key in ('netease:0','netease:01','netease:-1','netease:1/evil','netease:'+'1'*20):
                with self.subTest(key=key),self.assertRaises(ValueError):restored.set_source(key)
    def test_manual_position_and_persistence(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            controller=BeatController(root);controller.set_enabled(True);controller.set_source('bilibili:BVsynthetic:1')
            controller.set_manual(120,100,1)
            self.assertFalse(controller.sample(0,True).available)
            self.assertEqual(controller.sample(600,True).beat_index,1)
            self.assertEqual(controller.sample(850,False),controller.sample(850,True))
            self.assertAlmostEqual(controller.sample(850,False).phase,.5)
            controller.set_manual(120,100,.5)
            self.assertAlmostEqual(controller.sample(600,True).phase,.5)
            other=BeatController(root);other.set_source('bilibili:BVsynthetic:1')
            self.assertEqual(other.sample(850,False),controller.sample(850,True))
            other.set_source('bilibili:BVsynthetic:2');self.assertFalse(other.sample(850,True).available)
    def test_cache_fingerprint_and_no_sample_io(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            audio=Path(root)/'fixture.wav';make_wav(audio)
            c=BeatController(root);c.set_enabled(True);c.set_source('local:'+str(audio.resolve()));first=c.fingerprint
            c.analysis={'bpm':120,'beats_ms':[0,500,1000]}
            with patch.object(Path,'open',side_effect=AssertionError('sample must not read disk')):
                self.assertEqual(c.sample(750,True).beat_index,1)
                self.assertAlmostEqual(c.sample(750,False).phase,.5)
                self.assertEqual(c.sample(0,True).beat_index,0)
            with audio.open('ab') as file:file.write(b'changed')
            c.set_source('');c.set_source('local:'+str(audio.resolve()))
            self.assertNotEqual(first,c.fingerprint)
            self.assertFalse(c.analysis)
    def test_malformed_worker_messages(self):
        class FakeProcess:
            def readAllStandardOutput(self):
                return b'[]\nnull\n42\n{"type":"progress","progress":null}\n{"type":"progress","progress":true}\n{"type":"progress","progress":101}\n{"type":"progress","progress":55}\n{"type":"result","data":[]}\n'
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            c=BeatController(root);c.process=FakeProcess();c._output()
            self.assertEqual(c.progress,55);self.assertFalse(c.analysis)
            c.process=None
    def test_worker_start_failure_recovers(self):
        from unittest.mock import patch
        import time
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            audio=Path(root)/'fixture.wav';make_wav(audio)
            c=BeatController(root);c.set_enabled(True);c.set_source('local:'+str(audio.resolve()))
            with patch('music_beats.controller.sys.executable',str(Path(root)/'missing-python.exe')):
                c.analyze()
                end=time.monotonic()+3
                while c.process is not None and time.monotonic()<end:
                    self.app.processEvents();time.sleep(.01)
            self.assertIsNone(c.process)
            self.assertIn('无法启动',c.status)
            c.analyze();self.assertIsNotNone(c.process);c.cancel()
    def test_silence(self):
        with self.assertRaises(ValueError):estimate([0]*1000)
    def test_decode_wav(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'pulses.wav';make_wav(path)
            proc=subprocess.run([sys.executable,'-m','music_beats.worker',str(path)],capture_output=True,text=True,timeout=40,encoding='utf-8')
            messages=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
            results=[m['data'] for m in messages if m['type']=='result']
            self.assertTrue(results,(proc.stdout,proc.stderr))
            self.assertAlmostEqual(results[0]['bpm'],120,delta=3)

    def test_opposite_phase_stereo_does_not_become_silence(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'opposite-stereo.wav';make_wav(path,rate=48000,channels=2,anti_phase=True)
            proc=subprocess.run([sys.executable,'-m','music_beats.worker',str(path)],capture_output=True,text=True,timeout=20,encoding='utf-8')
            messages=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')]
            results=[m['data'] for m in messages if m['type']=='result']
            self.assertEqual(len(results),1,(proc.stdout,proc.stderr))
            self.assertFalse(any(m['type']=='error' for m in messages))
            self.assertAlmostEqual(results[0]['bpm'],120,delta=3)
            self.assertAlmostEqual(results[0]['duration_ms'],8000,delta=20)

    def test_invalid_audio_emits_one_failure_without_later_analysis(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/'broken.mp3';path.write_bytes(b'not an audio file')
            proc=subprocess.run([sys.executable,'-m','music_beats.worker',str(path)],capture_output=True,text=True,timeout=10,encoding='utf-8')
            terminal=[json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{')
                      and json.loads(line).get('type') in ('error','result')]
            self.assertEqual(len(terminal),1,(proc.stdout,proc.stderr))
            self.assertEqual(terminal[0]['type'],'error')

def make_wav(path,rate=22050,channels=1,anti_phase=False):
    with wave.open(str(path),'wb') as audio:
        audio.setparams((channels,2,rate,0,'NONE','not compressed'))
        samples=[]
        for i in range(rate*8):
            t=i%int(rate*.5)
            value=.8*math.sin(2*math.pi*700*i/rate)*(1-t/(rate*.025)) if t<rate*.025 else 0
            samples.append(b''.join(struct.pack('<h',round(value*32767)*(-1 if anti_phase and c%2 else 1)) for c in range(channels)))
        audio.writeframes(b''.join(samples))
if __name__=='__main__':unittest.main()
