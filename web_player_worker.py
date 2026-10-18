"""Dedicated WebView2 window. JSON pipe commands manage only this owned window."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

from bilibili_links import video_url


PREFIX = 'TIANYI_WEB '


def emit(event):
    print(PREFIX + json.dumps(event, ensure_ascii=True), flush=True)


def run():
    import webview
    commands = queue.Queue()
    closed = threading.Event()
    script = (Path(__file__).parent / 'bilibili_probe.js').read_text(encoding='utf-8')
    self_test = '--self-test' in sys.argv
    fixture = ''
    if self_test:
        import base64
        import io
        import wave
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(bytes(8000 * 2 * 4))
        fixture = ('<title>天依网页播放测试</title><div class="bpx-player-video-wrap">'
                   '<video autoplay muted loop controls width="640" src="data:audio/wav;base64,' +
                   base64.b64encode(audio.getvalue()).decode() + '"></video></div>')
    window = webview.create_window('天依 · B站播放', html='<p>正在准备播放窗口…</p>',
                                   width=1024, height=720, min_size=(640, 480), focus=not self_test)
    window.events.closed += lambda: closed.set()
    minimizing = threading.Event()
    def on_minimize():
        minimizing.set()
        commands.put({'cmd': 'hide'})
    window.events.minimized += on_minimize
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    webview.settings['ALLOW_DOWNLOADS'] = False
    webview.settings['ALLOW_FILE_URLS'] = False

    def reader():
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    commands.put(value)
            except ValueError:
                pass
        commands.put({'cmd': 'close'})

    def loop():
        threading.Thread(target=reader, daemon=True).start()
        if not window.events.loaded.wait(20):
            emit({'type': 'fatal', 'message': '播放窗口未能完成初始化，请重新打开'})
            window.destroy()
            return
        from System import Func, Object
        early = (Path(__file__).parent / 'bilibili_early.js').read_text(encoding='utf-8')
        try:
            registration = window.native.Invoke(Func[Object](lambda:
                window.native.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(early)))
            registration.GetAwaiter().GetResult()
        except Exception as error:
            emit({'type': 'fatal', 'message': '网页初始化失败：' + str(error)[:160]})
            window.destroy()
            return
        current, token, command, volume, seek_position = '', '', None, 0.6, None
        started, next_probe, requested_play = 0, 0, False
        hidden, last_playing = False, False
        emit({'type': 'ready'})
        while not closed.is_set():
            try:
                item = commands.get(timeout=0.15)
            except queue.Empty:
                item = {}
            kind = item.get('cmd')
            if kind == 'close':
                window.destroy()
                return
            if kind == 'load':
                try:
                    selected = video_url(item.get('url'))
                except ValueError as error:
                    emit({'type': 'error', 'token': item.get('token'), 'message': str(error)})
                    continue
                restart = selected == current and item.get('restart') and window.events.loaded.is_set()
                if restart and not self_test:
                    try:
                        restart = video_url(window.get_current_url()) == selected
                    except ValueError:
                        restart = False
                current = selected
                token = str(item.get('token', ''))
                volume = max(0, min(1, float(item.get('volume', 0.6))))
                requested_play = True
                started = time.monotonic()
                command = 'restart' if restart else 'play'
                if restart:
                    pass
                elif self_test:
                    window.load_html(fixture)
                else:
                    window.load_url(current)
                    if not hidden:
                        window.show()
            elif kind in ('play', 'pause', 'seek'):
                command = kind
                seek_position = item.get('position') if kind == 'seek' else None
                requested_play = kind == 'play' if kind != 'seek' else requested_play
            elif kind == 'volume':
                volume = max(0, min(1, float(item.get('value', 0.6))))
            elif kind == 'show':
                hidden = False
                window.show()
                window.restore()
                emit({'type': 'visibility', 'hidden': False})
            elif kind == 'hide':
                if requested_play:
                    command = 'resume'
                hidden = True
                window.hide()
                minimizing.clear()
                emit({'type': 'visibility', 'hidden': True})
            elif kind == 'minimize':
                minimizing.set()
                window.minimize()
                continue
            now = time.monotonic()
            if not current or (not item and now < next_probe):
                continue
            next_probe = now + 0.7
            try:
                if not window.events.loaded.is_set():
                    if now - started > 30:
                        emit({'type': 'waiting', 'token': token, 'message': '网页仍在加载，请检查网络或在窗口完成验证'})
                    continue
                actual = window.get_current_url() or ''
                if not self_test and actual.startswith(('about:', 'data:')):
                    if now - started > 30:
                        emit({'type': 'waiting', 'token': token, 'message': '视频页面未能打开，请检查网络或重新选择歌曲'})
                    continue
                try:
                    same_video = self_test or video_url(actual) == current
                except ValueError:
                    same_video = self_test
                if not same_video:
                    # Do not interpret login pages or site auto-navigation as an ended track.
                    emit({'type': 'waiting', 'token': token, 'message': '网页已离开当前视频，请返回播放页或选择下一首'})
                    window.evaluate_js("document.querySelectorAll('video').forEach(v=>v.pause())")
                    continue
                config = {'token': token, 'command': command,
                          'position': seek_position, 'volume': volume}
                applied_command = command
                value = window.evaluate_js(script.replace('__CONFIG__', json.dumps(config)))
                if not isinstance(value, dict):
                    continue
                if not value.get('has_video'):
                    if self_test:
                        emit({'type': 'diagnostic', 'html': window.evaluate_js('document.body.innerHTML.slice(0, 1000)'),
                              'probe': value})
                    if now - started > 30:
                        emit({'type': 'waiting', 'token': token, 'message': '未检测到视频，请在网页完成登录/验证，或手动切下一首'})
                    continue
                command, volume, seek_position = None, None, None
                if (not hidden and not minimizing.is_set() and applied_command is None and
                        last_playing and not value.get('playing') and not value.get('ended')):
                    requested_play = False
                if requested_play and not value.get('seen_playing') and now - started < 15:
                    command = 'resume'
                if hidden and requested_play and value.get('paused') and not value.get('ended'):
                    command = 'resume'
                last_playing = bool(value.get('playing'))
                emit({'type': 'state', **value})
            except Exception as error:
                if time.monotonic() - started > 30:
                    emit({'type': 'waiting', 'token': token, 'message': '网页暂未就绪，请查看播放窗口'})
        emit({'type': 'closed'})

    storage = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TianyiPet' / 'WebPlayer'
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(loop, gui='edgechromium', private_mode=self_test, storage_path=str(storage))


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        emit({'type': 'fatal', 'message': '网页播放窗口启动失败，请确认已安装 Edge WebView2：' + str(error)[:200]})
        sys.exit(1)
