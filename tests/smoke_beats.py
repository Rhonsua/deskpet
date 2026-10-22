"""Real Qt MP3 decode, tagged metadata and cancellable controller integration."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['QT_MEDIA_BACKEND']='windows' # Match the application's inherited environment.
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from PySide6.QtWidgets import QApplication
from music_beats import BeatController
from tests.test_beats import make_wav

def run():
    app=QApplication.instance() or QApplication([])
    import imageio_ffmpeg # Test-only encoder already installed; never a runtime dependency.
    from mutagen.id3 import ID3,TBPM
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
        folder=Path(root);wav=folder/'synthetic.wav';mp3=folder/'synthetic.mp3';make_wav(wav)
        # Real-world regression: 48 kHz stereo MP3 encoder-delay frames stalled
        # Qt when the old worker forced 22.05 kHz mono output. The former mono
        # 22.05 kHz fixture never exercised that resampler path.
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-loglevel','error','-y','-i',str(wav),
                        '-ar','48000','-ac','2','-b:a','320k',str(mp3)],check=True,timeout=30)
        tags=ID3(str(mp3));tags.add(TBPM(encoding=3,text=['123']));tags.save(str(mp3))
        c=BeatController(folder);assert not c.enabled;c.set_enabled(True);c.set_source('local:'+str(mp3.resolve()))
        assert c.tag_bpm==123,c.tag_bpm
        assert c.sample(1000,True).available
        widget=c.create_widget();assert widget is not None
        from PySide6.QtWidgets import QCheckBox,QToolButton,QDoubleSpinBox
        checkbox=widget.findChild(QCheckBox);assert checkbox.isChecked()
        advanced=widget.findChild(QToolButton);assert not advanced.isChecked()
        checkbox.setChecked(False);assert not c.enabled and not c.sample(1000,True).available
        checkbox.setChecked(True);assert c.enabled
        assert not widget.findChild(QDoubleSpinBox).isVisibleTo(widget)
        advanced.setChecked(True);assert widget.findChild(QDoubleSpinBox).isVisibleTo(widget)
        c.analyze();end=time.monotonic()+40
        while c.process is not None and time.monotonic()<end:app.processEvents();time.sleep(.01)
        assert c.analysis,c.status
        assert abs(c.analysis['bpm']-120)<3,c.analysis['bpm']
        assert abs(c.analysis['duration_ms']-8000)<30,c.analysis['duration_ms']
        c.set_manual(100,200,2)
        copy=BeatController(folder);copy.set_source(c.source)
        assert copy.analysis and copy.manual['bpm']==100
        assert copy.sample(800,False)==copy.sample(800,True)
        c.analyze();c.cancel();assert c.process is None
        c.shutdown();copy.shutdown();widget.close()
        print('PASS: native 48 kHz stereo MP3 decode, ID3 BPM, duration, analysis cache, manual independence, pause, cancellation, widget')
if __name__=='__main__':run()
