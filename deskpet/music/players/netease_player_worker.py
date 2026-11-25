"""Official NetEase login in an isolated, disposable WebView2 profile."""
import base64
import hashlib
import json
import queue
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

from deskpet.music.netease.direct import COOKIE_NAMES, cookie_header, cookie_values, valid_cookie_value
from deskpet.music.netease.storage import protect, session_data
from deskpet.music.netease.login_progress import STATUS, WebScanProgress, qr_stage, record_login_progress

ORIGIN = 'https://music.163.com'
PREFIX = 'TIANYI_NETEASE_LOGIN '

# This probe reads only *visible* official login UI, including same-origin
# frames. The real page contains hidden success/expired templates at startup.
PAGE_PROBE = r'''(() => {
    if (location.origin !== 'https://music.163.com') return null;
    const visible = el => {
        const rect = el.getBoundingClientRect();
        const style = el.ownerDocument.defaultView.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility === 'visible' && style.display !== 'none';
    };
    const documents = [document];
    for (const f of document.querySelectorAll('iframe')) {
        try { if (visible(f) && f.contentDocument && f.contentWindow.location.origin === location.origin) documents.push(f.contentDocument); } catch (_) {}
    }
    let stage = null, renderedProfile = null;
    let dialogOpen = false, qrVisible = false, openRequested = false;
    for (const doc of documents) {
        try {
            const p = doc.defaultView.GUser;
            if (p && /^[1-9][0-9]{0,18}$/.test(String(p.userId))) {
                renderedProfile = {userId:String(p.userId), nickname:typeof p.nickname === 'string' ? p.nickname.slice(0,200) : ''};
            }
        } catch (_) {}
        for (const dialog of doc.querySelectorAll('.m-layer,.m-layer-w2,.m-login,[role="dialog"]')) {
            if (!visible(dialog) || !/登录|扫码|验证/.test(dialog.innerText)) continue;
            dialogOpen = true;
            if (!/扫码|二维码/.test(dialog.innerText)) continue;
            for (const image of dialog.querySelectorAll('canvas,img,svg')) {
                const rect = image.getBoundingClientRect();
                if (visible(image) && rect.width >= 96 && Math.abs(rect.width - rect.height) < 5 &&
                    (image.tagName !== 'IMG' || (image.complete && image.naturalWidth > 0))) qrVisible = true;
            }
        }
        for (const el of doc.querySelectorAll('.suc-txt,.confirm,.tip p')) {
            if (!visible(el)) continue;
            const text = el.innerText.trim();
            if (['登录成功', '授权成功', '已确认登录'].includes(text)) stage = 'confirmed';
            else if (stage !== 'confirmed' && (text === '请在手机上确认登录' || text === '扫描成功')) stage = 'scanned';
            else if (!stage && text === '二维码已失效') stage = 'expired';
        }
    }
    if (__OPEN_LOGIN__ && !dialogOpen && !stage && !renderedProfile) {
        for (const doc of documents) {
            if (doc.readyState === 'loading') continue;
            const trigger = Array.from(doc.querySelectorAll('[data-action="login"]')).find(visible);
            if (trigger) { trigger.click(); openRequested = true; break; }
        }
    }
    return JSON.stringify({stage, dialogOpen, qrVisible, openRequested, renderedProfile,
        documentId:String(performance.timeOrigin), profile:window.__tianyiLoginProbe || null});
})()'''

PROFILE_PROBE = r'''(() => {
    if (location.origin !== 'https://music.163.com') return;
    const state = {nonce:__NONCE__, profile:null, stage:'credential'};
    window.__tianyiLoginProbe = state;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    // Read the website's current-user declaration from a fresh copy of My Music.
    // A template keeps scripts, images and frames inert. Never execute returned HTML.
    function currentUser(html) {
        const template = document.createElement('template');
        template.innerHTML = html;
        for (const script of template.content.querySelectorAll('script:not([src])')) {
            const declaration = /(?:^|[;\n])\s*(?:var\s+GUser|window\.GUser)\s*=\s*\{/m.exec(script.textContent);
            if (!declaration) continue;
            const contents = script.textContent.slice(declaration.index + declaration[0].length);
            // The official page emits a JS object literal. Consume complete fields
            // so a nickname or another nested user's ID cannot be taken as the owner.
            const field = /\s*(?:"(\w+)"|'(\w+)'|(\w+))\s*:\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|true|false|null|-?\d+(?:\.\d+)?)\s*([,}])/y;
            let match, id = '', nickname = '';
            while ((match = field.exec(contents)) !== null) {
                const key = match[1] || match[2] || match[3];
                if (key === 'userId') id = match[4].replace(/^(['"])(.*)\1$/, '$2');
                if (key === 'nickname' && match[4].startsWith('"')) {
                    try { nickname = JSON.parse(match[4]).slice(0, 200); } catch (_) {}
                }
                if (match[5] === '}') break;
            }
            if (/^[1-9][0-9]{0,18}$/.test(id)) return {userId:id, nickname};
        }
        return null;
    }
    fetch('/my/', {credentials:'same-origin', cache:'no-store', redirect:'error', signal:controller.signal})
        .then(async response => {
            if (response.status === 401 || response.status === 403 || response.status === 429) {
                state.stage = 'verification_rejected';
                return;
            }
            if (!response.ok) {state.stage = 'verification_network'; return;}
            const url = new URL(response.url);
            if (url.origin !== location.origin || url.pathname !== '/my/') return;
            const html = await response.text();
            const owner = html.length <= 2 * 1024 * 1024 ? currentUser(html) : null;
            if (owner) state.profile = owner;
            else state.stage = 'verification_session';
        })
        .catch(() => {state.stage = 'verification_network';})
        .finally(() => clearTimeout(timer));
})()'''


def page_state(window, *, open_login=False):
    """Native JS evaluation: no Promise callback / pywebview bridge dependency."""
    value = window.run_js(PAGE_PROBE.replace('__OPEN_LOGIN__', 'true' if open_login else 'false'))
    if isinstance(value, str) and len(value) <= 4096:
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def official_page(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname == 'music.163.com'
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except (ValueError, TypeError):
        return False


def login_cookie(entries):
    """Choose valid cookie fields for the official origin, preferring its own domain."""
    values = {}
    for name, value, domain, path in entries:
        domain = domain.lower().lstrip('.')
        if (name in COOKIE_NAMES and domain in ('music.163.com', '163.com') and path in ('', '/')
                and value and valid_cookie_value(value) and (name not in values or domain == 'music.163.com')):
            values[name] = value
    return cookie_header('; '.join(f'{name}={value}' for name, value in values.items()))


class OfficialPage:
    """Bounded WebView2 operations on this window, including during a login redirect."""
    def __init__(self, window):
        from System import Func, Object
        self.native = window.native
        self.callback = Func[Object]

    def _result(self, start, finish):
        def on_official(action):
            core = self.native.webview.CoreWebView2
            if official_page(str(core.Source)):
                return action(core)
            return None
        task = self.native.Invoke(self.callback(lambda: on_official(start)))
        if task is None:
            return None
        # Wait off the UI thread. Neither navigation nor a missing JS bridge
        # should hold up the credential read or the user's close command.
        if not task.Wait(3000):
            raise TimeoutError()
        return self.native.Invoke(self.callback(lambda: on_official(lambda core: finish(task.Result))))

    def run_js(self, script):
        raw = self._result(lambda core: core.ExecuteScriptAsync(script), str)
        return json.loads(raw) if raw and len(raw) <= 16384 else None

    def cookie(self):
        def read(rows):
            return login_cookie((row.Name, row.Value, row.Domain, row.Path)
                                for row in rows if row.Name in COOKIE_NAMES)
        return self._result(lambda core: core.CookieManager.GetCookiesAsync(ORIGIN + '/'), read) or ''

    def reload(self):
        def refresh():
            core = self.native.webview.CoreWebView2
            if official_page(str(core.Source)):
                core.Reload()
            return None
        self.native.Invoke(self.callback(refresh))


def failure_event(step, error):
    # A source line identifies the failing operation without recording any
    # exception text, URL, account, QR, local variables or credentials.
    trace = error.__traceback__
    at = 0
    while trace:
        if trace.tb_frame.f_globals.get('__name__') == __name__:
            at = trace.tb_lineno
        trace = trace.tb_next
    return {'type':'fatal', 'step':step, 'at':at}


def emit(value):
    if not any(flag in sys.argv for flag in ('--self-test', '--probe-official', '--probe-login-flow')):
        record_login_progress(value)
    print(PREFIX + json.dumps(value, ensure_ascii=True), flush=True)


def run():
    import webview
    test = '--self-test' in sys.argv
    probe = '--probe-official' in sys.argv
    flow_probe = '--probe-login-flow' in sys.argv
    closed = threading.Event()
    commands = queue.Queue()
    site_events = queue.Queue()
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    webview.settings['ALLOW_DOWNLOADS'] = False
    webview.settings['ALLOW_FILE_URLS'] = False
    window = webview.create_window('网易云官方登录 · 正在打开扫码窗口',
        html='<p>正在打开网易云官方登录页面…</p>', width=1060, height=760,
        min_size=(800, 600), hidden=test or probe or flow_probe, on_top=False)
    window.events.closed += lambda: closed.set()

    def reader():
        for line in sys.stdin:
            if len(line) > 4096:
                continue
            try:
                value = json.loads(line)
                if isinstance(value, dict) and value.get('cmd') in ('close', 'check'):
                    commands.put(value['cmd'])
            except ValueError:
                pass
        commands.put('close')

    def loop():
        threading.Thread(target=reader, daemon=True).start()
        step = 'startup'
        scan = WebScanProgress()
        verification = None
        last_stage = None
        try:
            if not window.events.loaded.wait(25):
                raise RuntimeError('initialization')
            from System import Func, Object

            def configure():
                core = window.native.webview.CoreWebView2
                # Only the official top-level site may supply the accepted session.
                # Verification iframes remain handled by the real site/browser.
                def navigation(sender, args):
                    if not official_page(str(args.Uri)):
                        args.Cancel = True
                def popup(sender, args):
                    args.Handled = True
                core.NavigationStarting += navigation
                core.NewWindowRequested += popup
                core.Settings.AreDevToolsEnabled = False
                # Observe the site's own QR polling, without replacing requests,
                # reading their encrypted body, or exposing any QR key/Cookie.
                from System import Action
                from System.IO import Stream, StreamReader
                from System.Threading.Tasks import Task, TaskScheduler
                def response(sender, args):
                    address = str(args.Request.Uri)
                    path = urlsplit(address).path
                    if not official_page(address):
                        return
                    if path in ('/api/login/qrcode/unikey', '/weapi/login/qrcode/unikey'):
                        if args.Response.StatusCode == 200:
                            site_events.put('new_code')
                        return
                    if path not in ('/api/login/qrcode/client/login', '/weapi/login/qrcode/client/login'):
                        return
                    if args.Response.StatusCode != 200:
                        site_events.put('site_rejected')
                        return
                    def received(task):
                        try:
                            reader = StreamReader(task.Result)
                            try:
                                text = reader.ReadToEnd()
                            finally:
                                reader.Close()
                            if len(text) > 65536:
                                return
                            stage = qr_stage(json.loads(text))
                            if stage:
                                site_events.put(stage)
                        except Exception:
                            pass
                    try:
                        # Obtain the response on the WebView thread, read its blocking stream off it.
                        args.Response.GetContentAsync().ContinueWith(Action[Task[Stream]](received), TaskScheduler.Default)
                    except Exception:
                        # Navigation can retire an in-flight response. The visible official
                        # login dialog and My Music still report the site's result.
                        pass
                core.WebResourceResponseReceived += response
                return None
            window.native.Invoke(Func[Object](configure))
            source = OfficialPage(window)
            def current_url():
                # get_current_url is decorated with a 20-second loaded wait.
                # Read native Source instead while login may be navigating.
                try:
                    return str(window.native.Invoke(Func[Object](lambda: str(window.native.webview.CoreWebView2.Source))))
                except Exception:
                    return None
            if test:
                # Real same-origin fetch, iframe visibility, HttpOnly CookieManager
                # and encrypted handoff, without contacting the official site.
                from System import Array, Byte
                from System.IO import MemoryStream
                delayed_session = '--fixture-delayed-session' in sys.argv
                early_cookie = '--fixture-unverified-session' in sys.argv
                button_fixture = '--fixture-official-session' in sys.argv
                rendered_only = '--fixture-rendered-account' in sys.argv
                cookie_rotation = '--fixture-rotated-session' in sys.argv
                rotated = False
                document_loads = 0
                qr_checks = 0
                fixture_signed_in = False
                def fixture_resource(sender, args):
                    nonlocal document_loads, qr_checks, rotated
                    url = str(args.Request.Uri)
                    environment = window.native.webview.CoreWebView2.Environment
                    args.Response = environment.CreateWebResourceResponse(None, 404, 'Not Found', '')
                    if not official_page(url):
                        return
                    path = urlsplit(url).path
                    if path == '/my/':
                        # Only the regular website document in this synthetic WebView reveals its owner.
                        signed_in = (fixture_signed_in and not rendered_only
                                     and (not early_cookie or document_loads >= 2))
                        owner = 'userId:77,nickname:"合成网页登录测试"' if signed_in else 'nickname:"其他人,userId:99}"'
                        if cookie_rotation and signed_in and not rotated:
                            rotated = True
                            owner = 'userId:99'
                            fixture_cookie('synthetic-rotated')
                        content = '<html><script>var GUser={' + owner + '}; var other={userId:99};</script></html>'
                        mime = 'text/html; charset=utf-8'
                    elif path == '/weapi/login/qrcode/client/login':
                        qr_checks += 1
                        code = min(800 + qr_checks, 803) if button_fixture else 803
                        content = json.dumps({'code':code})
                        mime = 'application/json; charset=utf-8'
                    elif path == '/fixture-confirmed' and button_fixture and qr_checks >= 3:
                        fixture_cookie()
                        window.events.loaded.clear()
                        content, mime = '{}', 'application/json'
                    elif path == '/fixture-frame':
                        content = '<p class="confirm">请在手机上确认登录</p>'
                        if rendered_only or early_cookie:
                            # A stale rendered owner must not complete the next account's login.
                            user_id = 77 if document_loads >= 2 else 99
                            content += f'<script>var GUser={{userId:{user_id},nickname:"合成网页登录测试"}};</script>'
                        mime = 'text/html; charset=utf-8'
                    elif path == '/':
                        document_loads += 1
                        content = '<html><body><p class="suc-txt" style="display:none">扫描成功</p><iframe src="/fixture-frame"></iframe><script>window.pywebview=undefined;</script></body></html>'
                        if button_fixture:
                            # No modal or credential until the production opener finds the late login button.
                            content = """<button data-action="login" hidden>登录</button>
                                <section class="m-layer" hidden><h2>扫码登录</h2><canvas width="150" height="150"></canvas></section>
                                <script>
                                const button = document.querySelector('button');
                                setTimeout(() => button.hidden = false, 1300);
                                button.onclick = () => {
                                    document.querySelector('section').hidden = false;
                                    async function poll() {
                                        const response = await fetch('/weapi/login/qrcode/client/login', {method:'POST'});
                                        const result = await response.json();
                                        if (result.code === 803) setTimeout(() => fetch('/fixture-confirmed'), 1400);
                                        else setTimeout(poll, 1400);
                                    }
                                    poll();
                                };
                                </script>"""
                        elif delayed_session or early_cookie or rendered_only:
                            if document_loads == 1:
                                content = content.replace('</body>', """<p class="suc-txt" id="result"></p><script>
                                    fetch('/weapi/login/qrcode/client/login', {method:'POST'}).then(r => r.json()).then(r => {
                                        if (r.code === 803) document.getElementById('result').textContent = '登录成功';
                                    });</script></body>""")
                            elif delayed_session:
                                fixture_cookie()
                        mime = 'text/html; charset=utf-8'
                    else:
                        content, mime = '', 'text/plain'
                    stream = MemoryStream(Array[Byte](content.encode('utf-8')))
                    args.Response = environment.CreateWebResourceResponse(stream, 200, 'OK', 'Content-Type: ' + mime + '\r\nCache-Control: no-store')
                def fixture_setup():
                    window.native.webview.CoreWebView2.WebResourceRequested += fixture_resource
                    return None
                window.native.Invoke(Func[Object](fixture_setup))
                def fixture_cookie(value='synthetic-only'):
                    nonlocal fixture_signed_in
                    manager = window.native.webview.CoreWebView2.CookieManager
                    cookie = manager.CreateCookie('MUSIC_U', value, '.music.163.com', '/')
                    cookie.IsHttpOnly = True
                    cookie.IsSecure = True
                    manager.AddOrUpdateCookie(cookie)
                    fixture_signed_in = True
                    return None
                if not delayed_session and not button_fixture:
                    window.native.Invoke(Func[Object](fixture_cookie))
            step = 'navigate'
            window.load_url(ORIGIN + '/#/my/')
            emit({'type': 'ready'})
            opened_at = time.monotonic()
            deadline = opened_at + (35 if probe or flow_probe else 600)
            next_probe = 0
            probe_nonce = None
            probe_cookie = None
            reload_identity = None
            login_opened = bridge_disabled = qr_poll_waiting = False
            open_attempts = 0
            next_open = 0
            read_failed_since = None

            def status(stage):
                nonlocal last_stage
                if stage != last_stage:
                    message = STATUS[stage]
                    last_stage = stage
                    emit({'type':'status', 'stage':stage})
                    def update_title():
                        if not closed.is_set():
                            window.native.Text = '网易云官方登录 · ' + message
                        return None
                    try:
                        window.native.Invoke(Func[Object](update_title))
                    except Exception:
                        # The parent received the progress even if the form was closing.
                        pass
            while not closed.is_set() and time.monotonic() < deadline:
                manual_check = False
                try:
                    command = commands.get(timeout=1)
                    if command == 'close':
                        window.destroy()
                        return
                    if command == 'check':
                        next_probe = 0
                        manual_check = True
                        status('checking')
                except queue.Empty:
                    pass
                if not official_page(current_url()):
                    continue
                if test and not bridge_disabled and window.events.loaded.is_set():
                    source.run_js('window.pywebview = undefined;')
                    bridge_disabled = True
                if probe:
                    page = window.evaluate_js('({length:document.body.innerText.length, frames:document.querySelectorAll("iframe").length, links:document.links.length})')
                    emit({'type': 'probe_status', 'page': page})
                    if isinstance(page, dict) and page.get('length', 0) > 30 and page.get('links', 0) > 3:
                        emit({'type': 'probe', 'official_page_loaded': True})
                        window.destroy()
                        return
                    continue
                now = time.monotonic()
                try:
                    step = 'page'
                    state = page_state(source, open_login=not login_opened and open_attempts < 3 and now >= next_open)
                    step = 'cookie'
                    cookie = source.cookie()
                except Exception:
                    if closed.is_set():
                        return
                    if read_failed_since is None:
                        read_failed_since = now
                    if time.monotonic() - read_failed_since >= 15:
                        raise
                    status('page_reloading')
                    continue
                read_failed_since = None
                if state.get('openRequested'):
                    open_attempts += 1
                    next_open = now + 4
                if state.get('dialogOpen') or state.get('renderedProfile') or state.get('stage'):
                    login_opened = True
                prior_stage = scan.stage
                if (state.get('stage') == 'confirmed' or scan.stage not in ('confirmed', 'site_rejected')
                        and state.get('stage') in ('scanned', 'expired')):
                    scan.observe(state['stage'], now)
                while not site_events.empty():
                    stage = site_events.get_nowait()
                    login_opened = True
                    scan.site_result(stage, now)
                    qr_poll_waiting = stage == 'waiting'
                if flow_probe and qr_poll_waiting and state.get('qrVisible'):
                    emit({'type':'probe_flow', 'stage':'waiting', 'qr_visible':True, 'open_attempts':open_attempts})
                    window.destroy()
                    return
                if scan.stage != prior_stage and scan.stage in ('scanned', 'confirmed'):
                    status(scan.stage)
                step = 'account'
                profile = None
                auth = cookie_values(cookie).get('MUSIC_U')
                fingerprint = hashlib.sha256(auth.encode()).digest() if auth else None
                if fingerprint != probe_cookie:
                    probe_cookie, probe_nonce, next_probe = fingerprint, None, 0
                    reload_identity = None
                    verification = 'credential' if auth else None
                rendered = state.get('renderedProfile')
                document_id = state.get('documentId')
                site_challenge = scan.stage == 'site_rejected' and (state.get('dialogOpen') or not rendered)
                if auth and not site_challenge:
                    candidate = state.get('profile')
                    if isinstance(candidate, dict) and probe_nonce and candidate.get('nonce') == probe_nonce:
                        profile = candidate.get('profile')
                        if candidate.get('stage') in ('verification_session', 'verification_rejected', 'verification_network'):
                            verification = candidate['stage']
                    if reload_identity and document_id and reload_identity != document_id and rendered:
                        # A fresh official navigation with the same credentials can
                        # also establish the account (including JS-populated profiles).
                        profile = rendered
                    if profile and rendered and profile['userId'] == rendered['userId']:
                        profile['nickname'] = rendered.get('nickname') or profile.get('nickname', '')
                    allow_read = (verification != 'verification_rejected' and scan.stage != 'site_rejected'
                                  or manual_check or scan.stage == 'confirmed' and prior_stage != 'confirmed')
                    if not profile and now >= next_probe and allow_read:
                        probe_nonce = str(time.monotonic_ns())
                        next_probe = now + 15
                        try:
                            source.run_js(PROFILE_PROBE.replace('__NONCE__', json.dumps(probe_nonce)))
                        except Exception:
                            # The previous document may already be retired by the site.
                            verification = 'verification_network'
                if not profile:
                    pending, refresh = scan.without_session(now, manual_check, verification=verification,
                                                            qr_visible=bool(state.get('qrVisible')))
                    if not login_opened and verification is None and pending == 'waiting':
                        pending = 'opening' if now - opened_at < 15 else 'open_manually'
                    if (auth and rendered and not state.get('dialogOpen') and verification == 'verification_session'
                            and scan.stage not in ('confirmed', 'site_rejected') and reload_identity is None):
                        # Official login methods other than QR need not emit a phone confirmation.
                        refresh = True
                        pending = 'refresh_account_page'
                    status(pending)
                    if refresh:
                        reload_identity = document_id if auth else None
                        probe_nonce, next_probe = None, 0
                        step = 'navigate'
                        try:
                            source.reload()
                        except Exception:
                            # The site may already be changing documents after phone confirmation.
                            status('page_reloading')
                    continue
                if closed.is_set() or not official_page(current_url()):
                    continue
                # Re-read HttpOnly credentials after verification; a navigation or
                # cookie rotation must not hand off the earlier cookie snapshot.
                step = 'cookie'
                retry_until = time.monotonic() + 8
                while not closed.is_set():
                    try:
                        cookie = source.cookie()
                        break
                    except Exception:
                        if time.monotonic() >= retry_until:
                            raise
                        status('page_reloading')
                        closed.wait(.3)
                if closed.is_set():
                    return
                current_auth = cookie_values(cookie).get('MUSIC_U', '')
                if hashlib.sha256(current_auth.encode()).digest() != fingerprint:
                    continue
                step = 'handoff'
                session = session_data(dict(api='', uid=profile['userId'],
                    nickname=profile.get('nickname', ''), cookie=cookie), '')
                step = 'protect'
                token = base64.b64encode(protect(json.dumps(session).encode())).decode('ascii')
                step = 'handoff'
                emit({'type': 'session', 'protected': token})
                window.destroy()
                return
            if not closed.is_set():
                emit({'type': 'timeout', 'stage':last_stage})
                window.destroy()
        except Exception as error:
            if not closed.is_set():
                event = failure_event(step, error)
                event['stage'] = last_stage
                emit(event)
                window.destroy()

    # A fresh private profile for each attempt; remember-login stays in DPAPI only.
    with tempfile.TemporaryDirectory(prefix='tianyi-netease-login-', ignore_cleanup_errors=True) as directory:
        webview.start(loop, gui='edgechromium', private_mode=True, storage_path=directory)


def main():
    try:
        run()
    except Exception as error:
        emit(failure_event('startup', error))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
