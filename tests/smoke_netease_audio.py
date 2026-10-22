"""Real Windows audio-helper network playback with a synthetic silent WAV.

Uses only a temporary INI and loopback HTTP range server, volume zero + mute.
This proves the shared helper path, not HTTPS CDN playback or account rights.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from types import SimpleNamespace
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from audio.remote import AudioEngine


def main():
    app = QApplication.instance() or QApplication([])
    wav = BytesIO()
    with wave.open(wav, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b'\x00\x00' * 16000 * 12)
    payload = wav.getvalue()
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def handle(self):
            try:
                super().handle()
            except (ConnectionResetError, ConnectionAbortedError):
                pass  # Native media closes keep-alive sockets on seek/shutdown.

        def do_HEAD(self):
            self.serve(False)

        def do_GET(self):
            self.serve(True)

        def serve(self, body):
            received.append((self.command, self.headers.get('Range', '')))
            if self.path != '/synthetic-silence.wav':
                self.send_error(404)
                return
            start, end = 0, len(payload) - 1
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                if not match:
                    self.send_error(416)
                    return
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
                if not 0 <= start <= end < len(payload):
                    self.send_error(416)
                    return
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end - start + 1))
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
            self.end_headers()
            if body:
                try:
                    self.wfile.write(payload[start:end + 1])
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    states = []
    engine = None

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)

    def wait(predicate, label, seconds=12):
        deadline = time.monotonic() + seconds
        while not predicate() and not errors and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        if errors:
            raise AssertionError(f'{label}: {errors}')
        if not predicate():
            values = dict(engine.player.values) if engine else {}
            # No real stream address, credentials or user device ID in output.
            diagnostic = {key: values.get(key) for key in ('position', 'duration', 'state', 'status', 'seekable', 'error', 'error_text')}
            raise AssertionError(f'{label} timed out: {diagnostic}')

    try:
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / 'isolated-test.ini'), QSettings.Format.IniFormat)
            settings.setValue('audio_output_id', '')
            settings.setValue('audio_output_name', '')
            engine = AudioEngine(settings, Path(directory))
            engine.failed.connect(errors.append)
            engine.player.errorOccurred.connect(lambda error, message: errors.append(message))
            engine.player.mediaStatusChanged.connect(states.append)
            engine.audio.setVolume(0)
            engine.audio.setMuted(True)
            engine.start()
            try:
                wait(lambda: engine.ready, 'helper ready')
                player = engine.player
                player.setSource(QUrl(f'http://127.0.0.1:{server.server_port}/synthetic-silence.wav'))
                player.play()
                wait(lambda: player.duration() >= 11500 and player.position() >= 350
                     and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
                     'HTTP loaded and progressing')
                assert received, 'helper did not make an HTTP request'
                wait(player.isSeekable, 'HTTP seekable')
                player.pause()
                wait(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PausedState, 'pause')
                before = player.position()
                pump(.4)
                assert abs(player.position() - before) <= 180, 'pause did not freeze playback position'
                player.setPosition(8000)
                wait(lambda: abs(player.position() - 8000) <= 250, 'seek while paused')
                assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
                from music_tools.clock import playback_snapshot
                panel = SimpleNamespace(playback_source='netease', _player=player, engine=engine,
                    cloud_player=SimpleNamespace(current=dict(id='123', title='合成静音'),
                                                  media_ready=True, trial_offset=60000))
                snapshot = playback_snapshot(panel)
                assert snapshot.valid and not snapshot.playing
                assert abs(snapshot.position_ms - 68000) <= 250, 'trial position must be native milliseconds + millisecond offset'
                assert abs(snapshot.duration_ms - 72000) <= 500
                player.play()
                wait(lambda: player.position() >= 8500 and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, 'resume')
                player.setPosition(11000)
                wait(lambda: QMediaPlayer.MediaStatus.EndOfMedia in states, 'EndOfMedia', seconds=8)
                assert engine.audio.volume() == 0 and engine.audio.isMuted()
                print('NetEase audio-helper HTTP smoke OK: network load, silent playback, pause, seek, trial offset in ms, resume, EndOfMedia')
                print('Scope: Windows native audio helper + synthetic loopback WAV; real HTTPS CDN playback still requires user trial.')
            finally:
                engine.shutdown()
                pump(.05)
    finally:
        if engine is not None:
            engine.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
