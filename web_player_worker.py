"""Dedicated WebView2 window. JSON pipe commands manage only this owned window."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

from bilibili_links import video_url
from web_playback_guard import TailCompletion, ReplayRecovery


PREFIX = 'TIANYI_WEB '


def emit(event):
    print(PREFIX + json.dumps(event, ensure_ascii=True), flush=True)


def run():
    import webview
    commands = queue.Queue()
    closed = threading.Event()
    script = (Path(__file__).parent / 'bilibili_probe.js').read_text(encoding='utf-8')
    self_test = '--self-test' in sys.argv
    fixture = reload_fixture = ''
    if self_test:
        import base64
        import io
        import wave
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as wav:
            if '--self-test-history' in sys.argv:
                wav.setparams((1, 1, 4000, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes([128]) * (4000 * 210))
            else:
                wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(8000 * 2 * 4))
        fixture = ('<title>天依网页播放测试</title><div class="bpx-player-video-wrap">'
                   '<video autoplay muted loop controls width="640" src="data:audio/wav;base64,' +
                   base64.b64encode(audio.getvalue()).decode() + '"></video></div>')
        reload_fixture = fixture
        if '--self-test-history' in sys.argv:
            fixture += '''<script>
              const v = document.querySelector('video');
              v.addEventListener('loadedmetadata', () => {
                v.currentTime = v.duration - 3;
                setTimeout(() => {
                  v.currentTime = v.duration - 3;
                  document.title = '历史进度恢复到末尾';
                }, 1500);
              }, {once:true});
            </script>'''
            reload_fixture = fixture
        if '--self-test-faults' in sys.argv:
            # Reproduce missing ended and a site ignoring the first seek to zero.
            # This fixture is reachable only in the isolated self-test mode.
            fixture += '''<script>
              const v = document.querySelector('video');
              const clock = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentTime');
              const end = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'ended');
              const play = v.play.bind(v);
              let stuck = false, ignoreReset = true;
              Object.defineProperty(v, 'currentTime', {
                get() { return clock.get.call(v); },
                set(t) {
                  if (stuck && t === 0 && ignoreReset) { ignoreReset = false; return; }
                  if (t === 0) stuck = false;
                  clock.set.call(v, t);
                }
              });
              Object.defineProperty(v, 'ended', {get() { return !stuck && end.get.call(v); }});
              v.play = () => stuck ? Promise.resolve() : play();
              v.addEventListener('timeupdate', () => {
                if (!stuck && !v.seeking && v.currentTime > v.duration - .35) {
                  stuck = true;
                  v.pause();
                  clock.set.call(v, v.duration - .06);
                }
              });
            </script>'''
            if '--self-test-reload' in sys.argv:
                fixture = fixture.replace('ignoreReset = true', 'ignoreReset = 4').replace(
                    'ignoreReset = false; return;', 'ignoreReset -= 1; return;')
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
        desired_volume = 0.6
        started, next_probe, requested_play = 0, 0, False
        hidden, last_playing = False, False
        tail, replay = TailCompletion(), ReplayRecovery()
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
                desired_volume = volume
                last_playing = False
                requested_play = True
                started = time.monotonic()
                # Every explicitly selected track starts at zero, including
                # navigation/reopening, which can restore Bilibili history.
                command = 'restart'
                tail.reset()
                replay.start(started, settle_for=15)
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
                tail.reset()
                if kind in ('pause', 'seek'):
                    replay.cancel()
            elif kind == 'volume':
                volume = max(0, min(1, float(item.get('value', 0.6))))
                desired_volume = volume
            elif kind == 'show':
                hidden = False
                window.show()
                window.restore()
                emit({'type': 'visibility', 'hidden': False})
            elif kind == 'hide':
                if requested_play and command is None:
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
                if value.get('user_interacted') or not requested_play:
                    replay.cancel()
                recovering = replay.blocking
                action = replay.update(value, time.monotonic())
                recovering = recovering or replay.blocking
                if recovering:
                    # An old ended bit must not complete the new iteration.
                    value['ended'] = False
                    value['playing'] = False
                    value['starting_from_zero'] = True
                    tail.reset()
                if action == 'restart':
                    command = 'restart'
                elif action == 'reload':
                    # One bounded page reload if all same-page seeks failed.
                    # Keep the window hidden and retain the selected token.
                    started = time.monotonic()
                    command, volume = 'restart', desired_volume
                    replay.start(started, allow_reload=False, settle_for=15)
                    last_playing = False
                    if self_test:
                        window.load_html(reload_fixture)
                    else:
                        window.load_url(current)
                    emit({'type': 'waiting', 'token': token,
                          'message': '重播未能回到开头，正在重新载入当前视频…'})
                    continue
                elif action == 'failed':
                    requested_play = False
                    emit({'type': 'waiting', 'token': token,
                          'message': '重播仍未成功，请显示网页检查网络、登录或播放提示'})
                    continue
                if (not hidden and not minimizing.is_set() and applied_command is None and
                        not recovering and last_playing and not value.get('playing') and not value.get('ended')):
                    requested_play = False
                if not recovering and tail.update(value, time.monotonic(), requested_play):
                    value['ended'] = True
                    value['completion_reason'] = 'tail_stalled'
                if not requested_play:
                    # A pause command wins even when it races the end of media.
                    value['ended'] = False
                if command is None and requested_play and not value.get('seen_playing') and now - started < 15:
                    command = 'resume'
                if command is None and hidden and requested_play and value.get('paused') and not value.get('ended'):
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
