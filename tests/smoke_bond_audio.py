"""One tiny synthetic MP3, muted decode/seek/pause/cache. No real settings."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_MEDIA_BACKEND']='windows'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import math,struct,wave,time,tempfile,subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from deskpet.music.beats.controller import BeatController
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.chart import generate
from deskpet.mods.bond.rhythm import RhythmGame
from deskpet.mods.bond.playback import ClipPlayer
from deskpet.mods.bond.activities import Scanner


def run():
    app=QApplication([])
    def wait(predicate,timeout=12):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:app.processEvents();time.sleep(.01)
        assert predicate(),'Timed out waiting for local audio'
    with tempfile.TemporaryDirectory(prefix='bond-audio-') as directory:
        root=Path(directory);wav=root/'合成拍点.wav';mp3=root/'合成拍点.mp3'
        samples=[int(10000*math.exp(-(i%4000)/180)*math.sin(math.tau*440*i/8000)) for i in range(320000)]
        with wave.open(str(wav),'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(struct.pack('<'+'h'*len(samples),*samples))
        import imageio_ffmpeg
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-i',str(wav),'-ar','48000','-ac','2',str(mp3)],check=True,timeout=20)
        store=BondStore(root/'bond.db');controller=BeatController(root)
        game=None;clip=None
        try:
            controller.set_source('local:'+str(mp3));controller.analyze();wait(lambda:not controller.analyzing)
            assert controller.analysis['features_version']==2
            saved=BeatController(root);saved.set_source('local:'+str(mp3));assert saved.analysis==controller.analysis
            saved.shutdown()
            mod=SimpleNamespace(active=True,store=store,games=[],context=SimpleNamespace(data_dir=root),finish_round=Mock())
            mod.services=SimpleNamespace(snapshot=lambda **_:dict(playing=False,volume=0,beats={},beat_source=''),
                audio_claim=lambda:'token',audio_valid=lambda token:token=='token',audio_release=Mock(),act=Mock())
            chart=generate(controller.analysis,source=str(mp3),offset=5,duration=30,difficulty='normal',seed=12)
            game=RhythmGame(mod,str(mp3),chart=chart);game.setAttribute(Qt.WA_DeleteOnClose,False);game.sound.setChecked(False)
            game.start();wait(lambda:game.started is not None and game.now()>.2)
            game.pause();paused=game.elapsed;wait(lambda:game.player.playbackState()!=game.player.PlaybackState.PlayingState)
            assert game.paused and abs(game.elapsed-paused)<.1
            game.resume();wait(lambda:game.now()>paused+.15);game.close();mod.finish_round.assert_not_called()
            clip=ClipPlayer(mod,None);finished=[];failed=[];clip.finished.connect(lambda:finished.append(True));clip.failed.connect(failed.append)
            clip.play(str(mp3),2,.4);wait(lambda:bool(finished) or bool(failed));assert finished and not failed,failed
            clip.play(str(mp3),4,.4);wait(lambda:len(finished)==2 or bool(failed));assert len(finished)==2 and not failed,failed
            scanner=Scanner([str(mp3)],None);tracks=[];scanner.scanned.connect(lambda rows:tracks.extend(rows));scanner.start()
            wait(lambda:not scanner.isRunning());app.processEvents();assert tracks and tracks[0]['title']=='合成拍点'
            print('PASS: muted MP3 decode, cached features, generated chart, audio-clock seek/pause/resume, repeat clip, metadata scanner')
        finally:
            if game:game.close()
            if clip:clip.stop()
            controller.shutdown();store.close()


if __name__=='__main__':run()
