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
from audio.routing import AudioRouter, device_id
from audio.output_switch import OutputSwitch


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
    generation = 0
    switching = OutputSwitch(player, audio)
    router.routeWillChange.connect(switching.before_change)
    router.routeChanged.connect(switching.after_change)
    router.refresh()

    def device(value):
        return {'id': device_id(value), 'name': value.description()}

    def report():
        pending = switching.pending
        emit({'type': 'state', 'generation': generation,
              'position': pending.position if pending else player.position(),
              'playback_rate': player.playbackRate(),
              'duration': player.duration(), 'state': (pending.state if pending else player.playbackState()).value,
              'status': player.mediaStatus().value, 'seekable': player.isSeekable(),
              'error': player.error().value, 'error_text': player.errorString(),
              'volume': audio.volume(), 'muted': audio.isMuted(), 'device': device(audio.device()),
              'outputs': [device(output) for output in router.outputs], 'default': device(router.default),
              'preferred': router.preferred, 'fallback': router.fallback, 'summary': router.summary})

    def poll():
        nonlocal generation
        while not commands.empty():
            item = commands.get_nowait()
            kind = item.get('cmd')
            if kind == 'close':
                switching.cancel()
                player.stop()
                app.quit()
                return
            if kind == 'source':
                generation = item['generation']
                switching.cancel()
                player.setSource(QUrl(item['url']))
            elif kind == 'play':
                switching.play()
            elif kind == 'pause':
                switching.pause()
            elif kind == 'stop':
                switching.cancel()
                player.stop()
            elif kind == 'seek':
                switching.seek(int(item['position']))
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
