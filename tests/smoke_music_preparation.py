"""Real beat worker + synthetic transfer, no account or downloaded music."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from music_beats import BeatController
from music_tools.preparation import MusicPreparation
from tests.test_beats import make_wav


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='beat-gate-') as directory:
        owner = QObject()
        owner.root = Path(directory)
        panel = QWidget()
        panel.status = QLabel()
        owner.pet = SimpleNamespace(panel=panel)
        owner.beats = BeatController(owner.root, owner)
        preparation = MusicPreparation(owner)
        callbacks = []
        def wait():
            until = time.monotonic() + 40
            while preparation.pending and time.monotonic() < until:
                app.processEvents()
                time.sleep(.01)
            assert not preparation.pending, owner.beats.status
        try:
            audio = owner.root / 'synthetic.wav'
            make_wav(audio)
            preparation.local(audio, lambda: callbacks.append('disabled'))
            assert callbacks == ['disabled'] and not owner.beats.analyzing
            owner.beats.set_enabled(True)
            preparation.local(audio, lambda: callbacks.append('local'))
            assert preparation.pending and callbacks == ['disabled']
            wait()
            assert callbacks[-1] == 'local' and owner.beats.has_timing()
            with patch.object(owner.beats, 'analyze') as analyze:
                preparation.local(audio, lambda: callbacks.append('local-cached'))
                analyze.assert_not_called()
                assert callbacks[-1] == 'local-cached'
            item = dict(id='123', title='人工节拍测试')
            media = dict(size=audio.stat().st_size, duration_ms=8000, extension='wav', trial=False,
                         url='https://m10.music.126.net/synthetic.wav')
            def transfer(url, folder, stem, extension, **kwargs):
                target = Path(folder) / 'synthetic.wav'
                target.write_bytes(audio.read_bytes())
                preparation.transfer.completed.emit(str(target), '')
            with patch.object(preparation.transfer, 'start', side_effect=transfer) as download:
                preparation.online(item, media, lambda: callbacks.append('online'))
                wait()
                download.assert_called_once()
            assert callbacks[-1] == 'online' and owner.beats.has_timing()
            assert not list((owner.root / 'beat-work').iterdir()), 'temporary analysis audio must be removed'
            owner.beats.set_source('')
            with patch.object(preparation.transfer, 'start') as download:
                preparation.online(item, media, lambda: callbacks.append('online-cached'))
                download.assert_not_called()
                assert callbacks[-1] == 'online-cached'
            # A source/account switch cancels the callback before any late finish.
            uncached = owner.root / 'new.wav'
            make_wav(uncached)
            with patch.object(owner.beats, 'analyze'):
                preparation.local(uncached, lambda: callbacks.append('must-not-play'))
                assert preparation.pending
                preparation.cancel()
                owner.beats.analysisFinished.emit(True)
                assert callbacks[-1] != 'must-not-play'
                preparation.local(uncached, lambda: callbacks.append('disabled-during-wait'))
                owner.beats.set_enabled(False)
                assert callbacks[-1] == 'disabled-during-wait' and not preparation.pending
            print('PASS: pre-play analysis, local/online cache reuse, temporary audio cleanup, cancellation, disable-to-continue')
        finally:
            preparation.cancel()
            owner.beats.shutdown()
            panel.close()
            app.processEvents()


if __name__ == '__main__':
    main()
