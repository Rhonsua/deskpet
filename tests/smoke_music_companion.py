"""Integrated music tools, synthetic lyrics and owned playback reports only."""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox
from main import Pet
from audio.remote import RemotePlayer
from visual_style import APPEARANCE_REVISION


class Startup:
    supported = False
    def enabled(self): return False


class AudioStub(QObject):
    def __init__(self):
        super().__init__()
        self.ready = True
        self.generation = 0
        self.last_report = time.monotonic()
        self.commands = []
    def send(self, command): self.commands.append(command)
    def shutdown(self): pass


app = QApplication([])
font = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
families = QFontDatabase.applicationFontFamilies(font)
if families: app.setFont(QFont(families[0], 9))
with tempfile.TemporaryDirectory(prefix='music-companion-') as temporary:
    root = Path(temporary)
    settings = QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('character_selection', 'refined')
    settings.setValue('appearance_revision', APPEARANCE_REVISION)
    song = root / '人工合成测试.mp3'
    song.write_bytes(b'fixture without copyrighted audio')
    song.with_suffix('.lrc').write_text('[00:00.00]第一句测试\n[00:01.00]第二句测试\n[00:02.00]第三句测试', encoding='utf-8')
    pet = Pet(data_dir=root, settings=settings, startup=Startup())
    companion = pet.music_companion
    try:
        assert companion is not None, pet.music_startup_error
        assert companion.cloud is None
        pet.panel.progress_timer.stop()
        engine = AudioStub()
        player = RemotePlayer(engine)
        player.setSource(QUrl.fromLocalFile(str(song)))
        player.values.update(state=1, status=5, duration=3000, position=0)
        pet.panel.engine = engine
        pet.panel._player = player
        pet.playing = True
        before = dict(pet.panel.store.pet())
        companion.tick()
        assert companion.lyrics.overlay.text == '第一句测试'
        companion.beats.set_enabled(True)
        companion.beats.set_manual(120)
        player.values['position'] = 1250
        companion.tick()
        assert companion.lyrics.overlay.text == '第二句测试'
        assert companion.beat.available and companion.beat.beat_index == 2
        assert abs(companion.beat.phase - .5) < .001
        pet.set_mode('sleep')
        assert pet.current_music_beat(pet.behavior.activity) is None
        pet.behavior.begin_drag()
        assert pet.current_music_beat('lift') is None
        pet.behavior.end_drag(False)
        assert pet.behavior.mode == 'sleep'
        pet.set_mode('sing')
        player.values['state'] = 2
        companion.tick()
        sample = companion.beat
        companion.tick()
        assert companion.beat == sample and companion.lyrics.overlay.text == '第二句测试'
        player.values['position'] = 100
        companion.tick()
        assert companion.lyrics.overlay.text == '第一句测试'
        # A stopped/expired helper cannot leave a false subtitle on screen.
        engine.last_report = time.monotonic() - 5
        companion.tick()
        assert not companion.lyrics.overlay.isVisible() and companion.lyrics.source_key.startswith('local:')
        engine.last_report = time.monotonic()
        companion.open(0)
        assert companion.window.isVisible() and companion.cloud is not None
        assert companion.cloud.client.reply is None  # Opening a page never makes a network request.
        with patch('music_tools.companion.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            companion.online_lyrics('123', '人工云歌曲', '[00:00.00]云歌词测试\n[00:01.00]云歌词测试二')
        assert companion.bindings['123'] == 'local:' + str(song)
        assert companion.lyrics.store.binding(companion.snapshot.source_key)['song_id'] == '123'
        # Cloud binding actually switches back from web to the existing local player.
        pet.panel.playback_source = 'web'
        companion.play_bound('123')
        assert pet.panel.playback_source == 'local'
        assert any(command['cmd'] == 'play' for command in engine.commands)
        assert dict(pet.panel.store.pet()) == before
        preview = Path(__file__).resolve().parents[1] / 'preview'
        preview.mkdir(exist_ok=True)
        for index, name in enumerate(('netease-page', 'music-lyrics-page', 'music-beats-page')):
            companion.tabs.setCurrentIndex(index)
            app.processEvents()
            assert companion.window.grab().save(str(preview / (name + '.png')))
        # The playback intent survives pre-play analysis: pause stays paused,
        # and a late analysis result cannot restart a replaced local source.
        deferred = root / '首次准备测试.mp3'
        deferred.write_bytes(b'synthetic undecoded placeholder')
        with patch.object(companion.beats, 'analyze'):
            engine.commands.clear()
            pet.panel.queue.reset([str(deferred)], 0)
            pet.panel.start_track(0)
            assert companion.preparation.pending
            assert not any(command['cmd'] == 'play' for command in engine.commands)
            pet.panel.toggle()
            assert not pet.panel.autoplay_requested
            companion.beats.analysisFinished.emit(False)
            assert not any(command['cmd'] == 'play' for command in engine.commands)
            pet.panel.toggle()
            assert companion.preparation.pending
            pet.panel.activate_local()
            pet.panel.queue.reset([str(song)], 0)
            pet.panel.start_track(0)
            count = sum(command['cmd'] == 'play' for command in engine.commands)
            companion.beats.analysisFinished.emit(True)
            assert count == sum(command['cmd'] == 'play' for command in engine.commands)
        print('PASS: lazy tools; real clock/lyrics; beat state priority; cloud binding; pre-play pause and source-switch guard; no rewards/network')
    finally:
        if companion: companion.shutdown()
        if pet.mod_host: pet.mod_host.shutdown()
        pet.timer.stop()
        pet.panel.progress_timer.stop()
        pet.panel.bilibili.shutdown()
        pet.panel.shutdown_audio()
        pet.close_live2d()
        pet.panel.store.close()
        pet.tray.hide()
        pet.panel.hide()
        pet.hide()
