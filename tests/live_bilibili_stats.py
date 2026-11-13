"""Opt-in real Bilibili/WebView2 check, muted and using a disposable profile.

python -B tests/live_bilibili_stats.py --live-network
The worker wrappers only mute/log; playback uses the production implementation.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TRACE_SCRIPT = r'''(() => {
  const rows = [];
  const selected = () => Array.from(document.querySelectorAll(
    '.bpx-player-video-wrap video, .bilibili-player-video video, .bpx-player-container video, .bpx-player-container bwp-video'))
    .filter(v => typeof v.play === 'function').sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];
  const capture = event => {
    const v = selected();
    if (!v) return;
    rows.push({clock:performance.now()/1000, event,
      position:Number.isFinite(v.currentTime)?v.currentTime:0,
      duration:Number.isFinite(v.duration)?v.duration:0,
      playing:!v.paused && !v.ended && v.readyState>=2,
      paused:v.paused, seeking:v.seeking, ready_state:v.readyState,
      restart_id:window.__tianyiVideoState?.restart_id ?? null});
    if (rows.length>2000) rows.splice(0,rows.length-2000);
  };
  window.__tianyiLiveTrace = {drain:() => rows.splice(0)};
  setInterval(() => capture('poll'), 100);
  for (const name of ['playing','pause','seeking','seeked','ended'])
    window.addEventListener(name, e => {if (e.target === selected()) capture(name);}, true);
})()'''


def worker():
    import webview
    from deskpet.music.players import web_player_worker as owned
    original_start, original_create = webview.start, webview.create_window
    original_update = owned.ReplayRecovery.update

    def create(*args, **kwargs):
        window = original_create(*args, **kwargs)
        evaluate = window.evaluate_js

        def probe(script, *args, **kwargs):
            result = evaluate(script, *args, **kwargs)
            if 'const config = ' in script and 'window.__tianyiVideoState' in script and isinstance(result, dict):
                config = json.loads(script.split('const config = ', 1)[1].split(';', 1)[0])
                owned.emit({'type': 'test-probe', 'at': time.monotonic(),
                            'command': config.get('command'), 'restart_id': config.get('restart_id'),
                            'sample': result})
                trace = evaluate('window.__tianyiLiveTrace ? window.__tianyiLiveTrace.drain() : []')
                owned.emit({'type':'test-trace', 'token':config['token'], 'rows':trace})
            return result
        window.evaluate_js = probe
        return window

    def start(func, *args, **kwargs):
        def muted_start():
            from System import Func, Object
            window = webview.windows[0]
            if not window.events.loaded.wait(25):
                owned.emit({'type': 'fatal', 'message': '静音初始化等待超时；没有加载 B站页面'})
                window.destroy()
                return
            def mute():
                core = window.native.webview.CoreWebView2
                core.IsMuted = True
                return bool(core.IsMuted)
            confirmed = bool(window.native.Invoke(Func[Object](mute)))
            owned.emit({'type': 'test-mute', 'browser_muted': confirmed})
            if not confirmed:
                window.destroy()
                return
            task = window.native.Invoke(Func[Object](lambda:
                window.native.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(TRACE_SCRIPT)))
            task.GetAwaiter().GetResult()
            func()
        return original_start(muted_start, *args, **kwargs)

    def recovery(self, value, now):
        action = original_update(self, value, now)
        if action:
            owned.emit({'type': 'test-recovery', 'token': value.get('token'), 'action': action,
                        'position': value.get('position'), 'target': self.target})
        return action
    webview.create_window, webview.start = create, start
    owned.ReplayRecovery.update = recovery
    owned.run()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live-network', action='store_true', required=True)
    parser.add_argument('--seconds', type=int, default=25)
    parser.add_argument('--focus-opening', action='store_true', help='100 ms page trace; observe 8 seconds per start')
    args = parser.parse_args()
    if args.focus_opening:
        args.seconds = 8
    if not args.focus_opening and not 20 <= args.seconds <= 60:
        parser.error('--seconds must be 20..60')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    from types import SimpleNamespace
    from PySide6.QtCore import QSettings, QProcess
    from PySide6.QtWidgets import QApplication
    from deskpet.app import MusicPanel
    from deskpet.music.players import bilibili_player
    app = QApplication([])
    started = time.monotonic()
    report = dict(started=datetime.now().astimezone().isoformat(), live_website=True,
                  observation_seconds=args.seconds, isolated_profile=True, rounds=[],
                  mute_confirmations=[], events=[], pause_resume=None)
    output = ROOT / 'local-work/reports' / ('bilibili-live-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch_path = None
    try:
        with tempfile.TemporaryDirectory(prefix='tianyi-live-bili-') as scratch:
            scratch_path = Path(scratch)
            os.environ['LOCALAPPDATA'] = scratch
            bilibili_player.worker_command = lambda _: (sys.executable, ['-B', str(Path(__file__).resolve()), '--worker'])
            panel = MusicPanel(SimpleNamespace(playing=False, set_variant=lambda _: None,
                set_auto_walk=lambda _: None, toggle_walk=lambda: None,
                set_auto_teleport=lambda _: None, open_mods=lambda: None),
                data_dir=Path(scratch) / 'data',
                settings=QSettings(str(Path(scratch) / 'test.ini'), QSettings.Format.IniFormat))
            web = panel.bilibili
            web.worker_args = ['--start-hidden']
            panel.volume.setValue(0)
            current = None
            original_handler, original_send = web.handle_event, web.send

            def receive(event):
                nonlocal current
                kind = event.get('type')
                if kind == 'test-mute':
                    report['mute_confirmations'].append(event['browser_muted'])
                elif kind == 'test-probe' and current is not None:
                    value = event['sample']
                    if value.get('token') == current['token']:
                        current['samples'].append(dict(t=round(time.monotonic() - current['start_clock'], 3),
                            command=event['command'], restart_id=event['restart_id'], **value))
                elif kind == 'test-trace' and current is not None and event.get('token') == current['token']:
                    current['trace'].extend(event['rows'])
                elif kind == 'test-recovery':
                    report['events'].append(dict(t=round(time.monotonic() - started, 3), **event))
                elif kind in ('waiting', 'error', 'fatal'):
                    report['events'].append(dict(t=round(time.monotonic() - started, 3), **event))
                original_handler(event)

            def send(value):
                if value.get('cmd') == 'load':
                    value = dict(value, volume=0, background=True)
                original_send(value)
            web.handle_event, web.send = receive, send

            def pump(seconds):
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    app.processEvents()
                    time.sleep(.02)

            def wait(condition, timeout=50):
                until = time.monotonic() + timeout
                while time.monotonic() < until:
                    app.processEvents()
                    if condition():
                        return True
                    time.sleep(.02)
                return False

            def observe(label, trigger=None):
                nonlocal current
                if trigger:
                    trigger()
                current = dict(label=label, token=web.latch.token, url=web.current_url,
                               start_clock=time.monotonic(), samples=[], trace=[], result='waiting')
                report['rounds'].append(current)
                print('START', label, flush=True)
                if not wait(lambda: web.playing and web.metrics.get('token') == current['token']):
                    current.update(result='blocked', message=web.note.text())
                else:
                    current['time_to_playing'] = round(time.monotonic() - current['start_clock'], 3)
                    current['first_position'] = web.metrics.get('position')
                    current['title'] = web.metrics.get('title')
                    pump(args.seconds)
                    current['result'] = 'observed'
                valid_start = False
                previous = None
                backwards = []
                for sample in current['samples']:
                    if not sample.get('has_video') or sample.get('duration', 0) <= 0:
                        continue
                    position = sample.get('position', 0)
                    if sample.get('playing') and not sample.get('seeking') and 0 <= position < 8:
                        valid_start = True
                    if (valid_start and previous and previous.get('position', 0) >= 2
                            and previous['position'] - position > .75):
                        backwards.append(dict(t=sample['t'], before=previous['position'], after=position,
                                              command=sample['command'], seeking=sample.get('seeking')))
                    previous = sample
                current.update(backwards=backwards, reset_to_start=sum(x['after'] <= 1.5 for x in backwards),
                               normal_start_seen=valid_start,
                               playback_samples=sum(bool(s.get('playing')) for s in current['samples']))
                anchor, previous = None, None
                opening_rows, opening_backwards = [], []
                for sample in current['trace']:
                    if anchor is None and sample['playing'] and sample['position'] < 8:
                        anchor = sample['clock']
                    if anchor is None:
                        continue
                    elapsed = sample['clock'] - anchor
                    if elapsed <= 3:
                        opening_rows.append(sample)
                    if previous and previous['position'] - sample['position'] > .25:
                        opening_backwards.append(dict(t=round(elapsed, 3), before=previous['position'],
                            after=sample['position'], event=sample['event'], restart_id=sample['restart_id']))
                    previous = sample
                current['opening'] = dict(first_3s_samples=len(opening_rows),
                    covered_3s=anchor is not None and previous['clock'] - anchor >= 3,
                    first_3s_backwards=[x for x in opening_backwards if x['t'] <= 3],
                    all_trace_backwards=opening_backwards, trace_samples=len(current['trace']))
                if opening_backwards:
                    current['result'] = 'rewind-detected'
                if backwards:
                    current['result'] = 'rewind-detected'
                if current['result'] == 'observed' and not valid_start:
                    current['result'] = 'start-unverified'
                current['elapsed'] = round(time.monotonic() - current.pop('start_clock'), 3)
                print('RESULT', json.dumps({k:v for k,v in current.items() if k not in ('samples', 'trace', 'token')}, ensure_ascii=False), flush=True)
                result = current['result'] == 'observed'
                current = None
                return result

            def finish_into(label, index):
                token = web.latch.token
                duration = web.metrics.get('duration', 0)
                if not duration:
                    return False
                # Intentionally skip to the tail to exercise real ended->next.
                # This seek is outside all opening observation intervals.
                web.send({'cmd':'seek', 'position':max(0, duration - 3)})
                if not wait(lambda: web.latch.token != token and web.queue.index == index, 35):
                    report['events'].append(dict(type='test-failure', message=label + ' 未产生预期自动切换'))
                    return False
                return observe(label)

            try:
                urls = ['https://www.bilibili.com/video/BV1zs411S7sz/',
                        'https://www.bilibili.com/video/BV1zM4m1r7JS/',
                        'https://www.bilibili.com/video/BV1AWGVztE8W/']
                report['video_urls'] = urls
                for url in urls:
                    web.input.setText(url)
                    if not web.add_link():
                        raise RuntimeError('Cannot add public test video')
                web.mode.setCurrentIndex(web.mode.findData('loop'))
                observe('首次启动：普通DISCO', lambda: web.play_row(0))
                observe('切换视频：霜雪千年', lambda: web.play_row(1))
                observe('同页重播：霜雪千年', lambda: web.play_row(1))
                web.stop()
                if not wait(lambda: web.process.state() == QProcess.ProcessState.NotRunning, 12):
                    raise RuntimeError('测试播放器未能正常退出')
                successful = observe('重新启动播放器：流光', lambda: web.play_row(2))
                if successful:
                    web.set_playing(False)
                    paused = wait(lambda: not web.playing, 10)
                    pump(2)
                    before = web.metrics.get('position', 0)
                    web.set_playing(True)
                    resumed = wait(lambda: web.playing, 12)
                    pump(5)
                    after = web.metrics.get('position', 0)
                    report['pause_resume'] = dict(paused=paused, resumed=resumed, before=before, after=after,
                                                 preserved=paused and resumed and after >= before - .75)
                    print('PAUSE_RESUME', json.dumps(report['pause_resume']), flush=True)
                    web.mode.setCurrentIndex(web.mode.findData('single'))
                    finish_into('自然结束后单曲循环：流光', 2)
                    web.mode.setCurrentIndex(web.mode.findData('loop'))
                    finish_into('自然结束后列表切歌：普通DISCO', 0)
            finally:
                web.watchdog.stop()
                web.shutdown()
                panel.shutdown_audio()
                panel.progress_timer.stop()
                panel.store.close()
                panel.hide()
                pump(.3)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        print('ERROR', report['error'], flush=True)
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        report['temporary_profile_removed'] = scratch_path is not None and not scratch_path.exists()
        report['summary'] = dict(rounds=len(report['rounds']),
            passed=sum(r['result'] == 'observed' for r in report['rounds']),
            samples=sum(len(r['samples']) for r in report['rounds']),
            backward_jumps=sum(len(r.get('opening', {}).get('all_trace_backwards', r.get('backwards', []))) for r in report['rounds']),
            first_3s_samples=sum(r.get('opening', {}).get('first_3s_samples', 0) for r in report['rounds']),
            first_3s_backwards=sum(len(r.get('opening', {}).get('first_3s_backwards', [])) for r in report['rounds']),
            page_trace_samples=sum(r.get('opening', {}).get('trace_samples', 0) for r in report['rounds']),
            resets_to_start=sum(sum(x['after'] <= 1.5 for x in r.get('opening', {}).get('all_trace_backwards', r.get('backwards', []))) for r in report['rounds']),
            automatic_recovery_actions=sum(e['type'] == 'test-recovery' for e in report['events']))
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('SUMMARY', json.dumps(report['summary'], ensure_ascii=False), flush=True)
        print('REPORT', output, flush=True)
        print('PROFILE_REMOVED', report['temporary_profile_removed'], flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if '--worker' in sys.argv:
        worker()
    else:
        main()
