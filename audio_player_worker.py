"""Native Qt audio in a separate process so endpoint discovery cannot freeze UI."""
import json
import os
import queue
import sys
import threading

os.environ.setdefault('QT_MEDIA_BACKEND', 'windows')
from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication
from audio_routing import AudioRouter, device_id


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    commands = queue.Queue()
    settings = QSettings(sys.argv[sys.argv.index('--settings') + 1], QSettings.Format.IniFormat)
    def emit(value):
        print('TIANYI_AUDIO ' + json.dumps(value, ensure_ascii=True), flush=True)
    def reader():
        for line in sys.stdin:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    commands.put(item)
            except ValueError:
                pass
        commands.put({'cmd': 'close'})
    threading.Thread(target=reader, daemon=True).start()
    audio = QAudioOutput()
    player = QMediaPlayer()
    player.setAudioOutput(audio)
    router = AudioRouter(audio, settings)
    generation, restore, routing = 0, None, False

    def before_route():
        nonlocal restore, routing
        if player.source().isEmpty():
            return
        restore = (player.source(), player.position(), player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        routing = True
        player.stop()
        player.setSource(QUrl())

    def after_route():
        nonlocal routing
        if restore:
            player.setSource(restore[0])
        routing = False
        restore_position()

    def restore_position(*_):
        nonlocal restore
        ready = player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia,
                                         QMediaPlayer.MediaStatus.BufferingMedia,
                                         QMediaPlayer.MediaStatus.BufferedMedia)
        if restore and not routing and ready and player.duration() > 0 and player.isSeekable():
            source, position, playing = restore
            restore = None
            if source == player.source():
                player.setPosition(position)
                if playing:
                    player.play()

    router.routeWillChange.connect(before_route)
    router.routeChanged.connect(after_route)
    player.durationChanged.connect(restore_position)
    player.seekableChanged.connect(restore_position)
    player.mediaStatusChanged.connect(restore_position)
    router.refresh()

    def device(value):
        return {'id': device_id(value), 'name': value.description()}

    def report():
        emit({'type': 'state', 'generation': generation, 'position': player.position(),
              'duration': player.duration(), 'state': player.playbackState().value,
              'status': player.mediaStatus().value, 'seekable': player.isSeekable(),
              'error': player.error().value, 'error_text': player.errorString(),
              'volume': audio.volume(), 'muted': audio.isMuted(), 'device': device(audio.device()),
              'outputs': [device(output) for output in router.outputs], 'default': device(router.default),
              'preferred': router.preferred, 'fallback': router.fallback, 'summary': router.summary})

    def poll():
        nonlocal generation, restore
        while not commands.empty():
            item = commands.get_nowait()
            kind = item.get('cmd')
            if kind == 'close':
                player.stop()
                app.quit()
                return
            if kind == 'source':
                generation = item['generation']
                restore = None
                player.setSource(QUrl(item['url']))
            elif kind == 'play':
                player.play()
            elif kind == 'pause':
                if restore:
                    restore = (restore[0], restore[1], False)
                player.pause()
            elif kind == 'stop':
                restore = None
                player.stop()
            elif kind == 'seek':
                player.setPosition(int(item['position']))
            elif kind == 'volume':
                audio.setVolume(float(item['value']))
            elif kind == 'muted':
                audio.setMuted(bool(item['value']))
            elif kind == 'output':
                router.choose(item['id'])
        report()

    emit({'type': 'ready'})
    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(100)
    app.exec()


if __name__ == '__main__':
    run()
