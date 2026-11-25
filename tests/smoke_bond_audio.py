"""Muted regular music plus activity audio. --full-show plays three entire local files."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_MEDIA_BACKEND']='windows'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import math,struct,wave,time,tempfile,subprocess,shutil
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QSettings,QUrl,QProcess
from deskpet.music.audio.remote import AudioEngine
from deskpet.music.beats.controller import BeatController
from deskpet.mods.bond.store import BondStore
from deskpet.mods.bond.chart import generate
from deskpet.mods.bond.rhythm import RhythmGame
from deskpet.mods.bond.playback import ClipPlayer
from deskpet.mods.bond.activities import Scanner,GuessGame,WeeklyShow


def run():
    app=QApplication([])
    def wait(predicate,timeout=20):
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
        settings=QSettings(str(root/'output.ini'),QSettings.IniFormat)
        ordinary_dir=root/'ordinary';ordinary_dir.mkdir()
        normal=AudioEngine(settings,ordinary_dir)
        normal.audio.setMuted(True);normal.audio.setVolume(0.)
        store=BondStore(root/'bond.db');controller=BeatController(root)
        game=clip=quiz=show=None
        def playing():
            return normal.player.playbackState()==normal.player.PlaybackState.PlayingState
        legacy=SimpleNamespace(snapshot=lambda **_:dict(playing=playing(),volume=0,beats={},beat_source=''),
            audio_claim=lambda:None if playing() else 'token',audio_valid=lambda t:t=='token',audio_release=Mock(),act=Mock())
        try:
            controller.set_source('local:'+str(mp3));controller.analyze();wait(lambda:not controller.analyzing)
            assert controller.analysis['features_version']==2
            saved=BeatController(root);saved.set_source('local:'+str(mp3));assert saved.analysis==controller.analysis
            saved.shutdown()
            # A long, small PCM fixture keeps ordinary music running through all three acts.
            normal_song=root/'普通歌单.wav'
            with wave.open(str(normal_song),'wb') as out:
                out.setparams((1,2,8000,0,'NONE',''));out.writeframes(bytes(16000*160))
            normal.start();normal.player.setSource(QUrl.fromLocalFile(str(normal_song)));normal.player.play()
            wait(lambda:playing() and normal.player.position()>200)
            mod=SimpleNamespace(active=True,store=store,games=[],context=SimpleNamespace(data_dir=root),
                                finish_round=Mock(),refresh=Mock(),after_growth=Mock(),services=legacy)
            chart=generate(controller.analysis,source=str(mp3),offset=5,duration=30,difficulty='normal',seed=12)
            game=RhythmGame(mod,str(mp3),chart=chart);game.setAttribute(Qt.WA_DeleteOnClose,False);game.sound.setChecked(False)
            before=normal.player.position()
            game.start();wait(lambda:game.started is not None and game.now()>.2)
            assert playing() and normal.player.position()>before
            game.pause();paused=game.elapsed
            player=game.transport.engine.player
            wait(lambda:player.playbackState()!=player.PlaybackState.PlayingState)
            assert game.paused and abs(game.elapsed-paused)<.1
            game.resume();wait(lambda:game.now()>paused+.15);game.close();mod.finish_round.assert_not_called()
            clip=ClipPlayer(mod,None);finished=[];failed=[];clip.finished.connect(lambda:finished.append(True));clip.failed.connect(failed.append)
            clip.play(str(mp3),2,.4);wait(lambda:bool(finished) or bool(failed));assert finished and not failed,failed
            clip.play(str(mp3),4,.4);wait(lambda:len(finished)==2 or bool(failed));assert len(finished)==2 and not failed,failed
            scanner=Scanner([str(mp3)],None);tracks=[];scanner.scanned.connect(lambda rows:tracks.extend(rows));scanner.start()
            wait(lambda:not scanner.isRunning());app.processEvents();assert tracks and tracks[0]['title']=='合成拍点'
            # Fail a real decode then retry successfully on the same helper.
            clip.play(str(root/'失效文件.mp3'),2,.4);wait(lambda:bool(failed))
            clip.play(str(mp3),2,.4);wait(lambda:len(finished)==3);assert len(failed)==1
            clip.close()
            paths=[mp3,root/'样曲乙.mp3',root/'样曲丙.mp3']
            for path in paths[1:]:shutil.copyfile(mp3,path)
            legacy.library=lambda:[dict(path=str(path)) for path in paths]
            quiz=GuessGame(mod);quiz.setAttribute(Qt.WA_DeleteOnClose,False);quiz.show()
            wait(quiz.start_button.isEnabled)
            quiz.start_button.click();wait(lambda:quiz.player.loaded)
            assert '正在试听' in quiz.question_title.text()
            normal.player.pause();wait(lambda:not playing())
            # Switch main tracks while the eight-second question continues.
            normal.player.setSource(QUrl.fromLocalFile(str(wav)));normal.player.play()
            wait(lambda:playing() and normal.player.position()>300)
            wait(lambda:quiz.clip_ready);assert quiz.question_progress.value()==80
            assert playing() and Path(normal.player.source().toLocalFile())==wav
            assert quiz.answers[0].isEnabled()
            quiz.close()
            print('PASS: mixed regular MP3/PCM and rhythm, pause/resume, bad file and retry, full eight-second quiz with ordinary track change',flush=True)
            if '--full-show' in sys.argv:
                pieces = [mp3, root/'桥.wav', root/'返场.wav']
                for path, seconds in zip(pieces[1:], (2.75, 5.25)):
                    with wave.open(str(path), 'wb') as out:
                        out.setparams((1, 2, 8000, 0, 'NONE', ''))
                        out.writeframes(bytes(round(seconds * 16000)))
                legacy.library = lambda: [dict(path=str(path)) for path in pieces]
                normal.player.setSource(QUrl.fromLocalFile(str(normal_song)));normal.player.play()
                wait(lambda:playing() and normal.player.position()>200)
                show=WeeklyShow(mod);show.setAttribute(Qt.WA_DeleteOnClose,False);show.show()
                wait(show.start_button.isEnabled)
                first, last = {}, {}
                def sample(seconds):
                    first.setdefault(show.index, seconds)
                    last[show.index] = seconds
                show.player.progress.connect(sample)
                # The container's duration is only an estimate. Both under- and
                # overreported lengths must be replaced by the playback clock.
                show.tracks[0]['duration'] = 3
                show.tracks[1]['duration'] = 70
                before = normal.player.position()
                show.start_button.click();wait(lambda:show.player.loaded)
                show.pause_button.click();assert show.player.paused
                ordinary_position=normal.player.position()
                wait(lambda:normal.player.position()>ordinary_position+300)
                assert show.player.paused
                show.pause_button.click()
                wait(lambda:show.complete or show.failed,65)
                assert show.complete and list(first)==[0,1,2],(first,show.label.text())
                for i, expected in enumerate((40., 2.75, 5.25)):
                    assert first[i] < 1.0 and abs(last[i]-expected) < .6, (i, first, last)
                    assert abs(show.program[i]['duration']-expected) < .25, show.program
                assert store.db.execute('SELECT COUNT(*) FROM shows').fetchone()[0]==1
                assert playing() and normal.player.position()-before > 47_000
                assert show.progress.value() == show.progress.maximum()
                print(f'PASS: full acts, first/last observed seconds {first} / {last}; one keepsake; ordinary music kept playing',flush=True)
        finally:
            if game:game.close()
            if clip:clip.close()
            if quiz:quiz.close()
            if show:show.close()
            normal.shutdown()
            wait(lambda: all(engine.process.state()==QProcess.NotRunning for engine in app.findChildren(AudioEngine)),5)
            controller.shutdown();store.close()


if __name__=='__main__':
    if '--packaged-worker' in sys.argv:
        exe=Path(__file__).resolve().parents[1]/'dist/TianyiPet/TianyiWorker.exe'
        assert exe.is_file()
        with patch('deskpet.music.audio.remote.worker_command',return_value=(str(exe),['--audio-worker'])):run()
    else:run()
