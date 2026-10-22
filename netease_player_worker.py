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

from netease_music.direct import COOKIE_NAMES, cookie_header
from netease_music.storage import protect, session_data
from netease_music.account_probe import AccountProbe

ORIGIN = 'https://music.163.com'
PREFIX = 'TIANYI_NETEASE_LOGIN '

# This probe reads only *visible* official login UI, including same-origin
# frames. The real page contains hidden success/expired templates at startup.
PAGE_PROBE = r'''(() => {
    if (location.origin !== 'https://music.163.com') return null;
    const documents = [document];
    for (const f of document.querySelectorAll('iframe')) {
        try { if (f.contentWindow.location.origin === location.origin) documents.push(f.contentDocument); } catch (_) {}
    }
    let stage = null, renderedProfile = null;
    for (const doc of documents) {
        try {
            const p = doc.defaultView.GUser;
            if (p && /^[1-9][0-9]{0,18}$/.test(String(p.userId))) {
                renderedProfile = {userId:String(p.userId), nickname:typeof p.nickname === 'string' ? p.nickname.slice(0,200) : ''};
            }
        } catch (_) {}
        for (const el of doc.querySelectorAll('.suc-txt,.confirm,.tip p')) {
            const s = doc.defaultView.getComputedStyle(el);
            if (!el.getClientRects().length || s.display === 'none' || s.visibility === 'hidden') continue;
            const text = el.innerText.trim();
            if (text === '请在手机上确认登录' || text === '扫描成功') stage = 'scanned';
            else if (text === '二维码已失效' && stage !== 'scanned') stage = 'expired';
        }
    }
    return JSON.stringify({stage, renderedProfile, profile:window.__tianyiLoginProbe || null});
})()'''

PROFILE_PROBE = r'''(() => {
    if (location.origin !== 'https://music.163.com') return;
    const nonce = __NONCE__;
    const state = {nonce, pending:true, profile:null};
    window.__tianyiLoginProbe = state;
    const csrf = (document.cookie.match(/(?:^|;\s*)__csrf=([^;]*)/) || [,''])[1];
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes)));
    const hex = bytes => Array.from(bytes, n => n.toString(16).padStart(2,'0')).join('');
    const encode = text => new TextEncoder().encode(text);
    async function aes(text, secret) {
        const key = await crypto.subtle.importKey('raw', encode(secret), 'AES-CBC', false, ['encrypt']);
        return b64(await crypto.subtle.encrypt({name:'AES-CBC', iv:encode('0102030405060708')}, key, encode(text)));
    }
    async function body() {
        const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        const fixedSecret = __FIXTURE_SECRET__;
        const secret = fixedSecret || Array.from(crypto.getRandomValues(new Uint8Array(16)), n => chars[n % chars.length]).join('');
        const first = await aes(JSON.stringify({csrf_token:csrf, e_r:false}), '0CoJUm6Qyw8W8jud');
        const params = await aes(first, secret);
        const spki = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDgtQn2JZ34ZC28NWYpAUd98iZ37BUrX/aKzmFbt7clFSs6sXqHauqKWqdtLkF2KexO40H1YTX8z2lSgBBOAxLsvaklV8k4cBFK9snQXE9/DDaFt6Rr7iVZMldczhC0JNgTz+SHXT6CBHuX3e9SdB1Ua44oncaTWz7OBGLbCiK45wIDAQAB';
        const rsa = await crypto.subtle.importKey('spki', Uint8Array.from(atob(spki), c => c.charCodeAt(0)), {name:'RSA-OAEP',hash:'SHA-256'}, true, ['encrypt']);
        const jwk = await crypto.subtle.exportKey('jwk', rsa);
        const n64 = jwk.n.replace(/-/g,'+').replace(/_/g,'/');
        const n = BigInt('0x' + hex(Uint8Array.from(atob(n64.padEnd(Math.ceil(n64.length/4)*4,'=')), c => c.charCodeAt(0))));
        let a = BigInt('0x' + hex(encode(secret.split('').reverse().join('')))), e = 65537n, out = 1n;
        while (e > 0n) { if (e & 1n) out = out * a % n; a = a * a % n; e >>= 1n; }
        return new URLSearchParams({params, encSecKey:out.toString(16).padStart(256,'0')}).toString();
    }
    body().then(payload => fetch('/weapi/w/nuser/account/get?csrf_token=' + encodeURIComponent(csrf), {
        method:'POST', credentials:'same-origin', redirect:'error',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body:payload, signal:controller.signal
    })).then(r => r.ok ? r.json() : null).then(d => {
        if (!d) return;
        const data = d.data && typeof d.data === 'object' ? d.data : d;
        const code = d.code === undefined ? data.code : d.code;
        const p = data.profile;
        if (code === 200 && p && /^[1-9][0-9]{0,18}$/.test(String(p.userId))) {
            state.profile = {userId:String(p.userId), nickname:typeof p.nickname === 'string' ? p.nickname.slice(0,200) : ''};
        }
    }).catch(() => {}).finally(() => {clearTimeout(timer); state.pending = false;});
})()'''


def page_state(window):
    """Native JS evaluation: no Promise callback / pywebview bridge dependency."""
    value = window.run_js(PAGE_PROBE)
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


def login_cookie(cookies):
    values = {}
    for jar in cookies:
        for name, morsel in jar.items():
            if (name in COOKIE_NAMES and morsel['domain'].lower().lstrip('.') in ('music.163.com', '163.com')
                    and morsel['path'] in ('', '/')):
                values[name] = morsel.value
    return cookie_header('; '.join(f'{name}={value}' for name, value in values.items()))


def emit(value):
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
    window = webview.create_window('网易云官方登录 · 点击网页右上角登录，完成后自动返回桌宠',
        html='<p>正在打开网易云官方登录页面…</p>', width=1060, height=760,
        min_size=(800, 600), hidden=test or probe or flow_probe, on_top=not (test or probe or flow_probe))
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
                from System.Threading.Tasks import Task
                def response(sender, args):
                    address = str(args.Request.Uri)
                    path = urlsplit(address).path
                    if not official_page(address) or path not in ('/api/login/qrcode/client/login', '/weapi/login/qrcode/client/login'):
                        return
                    if args.Response.StatusCode != 200:
                        site_events.put('site_rejected')
                        return
                    def received(task):
                        try:
                            reader = StreamReader(task.Result)
                            text = reader.ReadToEnd()
                            reader.Close()
                            if len(text) > 65536:
                                return
                            data = json.loads(text)
                            code = data.get('code')
                            stage = {800:'expired', 801:'waiting', 802:'scanned', 803:'confirmed'}.get(code)
                            if stage:
                                site_events.put(stage)
                            elif type(code) is int and code != 200:
                                site_events.put('site_rejected')
                        except Exception:
                            pass
                    args.Response.GetContentAsync().ContinueWith(Action[Task[Stream]](received), window.native.browser.syncContextTaskScheduler)
                core.WebResourceResponseReceived += response
                return None
            window.native.Invoke(Func[Object](configure))
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
                def fixture_resource(sender, args):
                    url = str(args.Request.Uri)
                    if not official_page(url):
                        return
                    if urlsplit(url).path == '/weapi/w/nuser/account/get':
                        # Check real AES-CBC/RSA form encoding with .NET's native
                        # AES decryptor and an explicitly synthetic fixed secret.
                        from urllib.parse import parse_qs
                        from System.IO import StreamReader
                        from System.Security.Cryptography import Aes
                        from System.Text import Encoding
                        reader = StreamReader(args.Request.Content)
                        values = parse_qs(reader.ReadToEnd())
                        def decrypt(value, secret):
                            cipher = Aes.Create()
                            cipher.Key = Encoding.UTF8.GetBytes(secret)
                            cipher.IV = Encoding.UTF8.GetBytes('0102030405060708')
                            encoded = base64.b64decode(value)
                            data = Array[Byte](encoded)
                            transform = cipher.CreateDecryptor()
                            result = transform.TransformFinalBlock(data, 0, len(encoded))
                            cipher.Dispose()
                            return str(Encoding.UTF8.GetString(result))
                        inner = decrypt(values['params'][0], 'fixture-secret16')
                        decoded = json.loads(decrypt(inner, '0CoJUm6Qyw8W8jud'))
                        import re
                        public = base64.b64decode(re.search(r"const spki = '([^']+)'", PROFILE_PROBE).group(1))
                        start = public.index(b'\x02\x81\x81\x00') + 4
                        modulus = int.from_bytes(public[start:start + 128], 'big')
                        expected_rsa = format(pow(int.from_bytes(b'fixture-secret16'[::-1], 'big'), 65537, modulus), '0256x')
                        if decoded != {'csrf_token':'', 'e_r':False} or values['encSecKey'][0] != expected_rsa:
                            raise ValueError('synthetic encryption mismatch')
                        content = json.dumps({'code':200, 'data':{'profile':{'userId':77, 'nickname':'合成网页登录测试'}}})
                        mime = 'application/json; charset=utf-8'
                    elif urlsplit(url).path == '/fixture-frame':
                        content = '<p class="confirm">请在手机上确认登录</p>'
                        if '--fixture-fetch' not in sys.argv:
                            content += '<script>var GUser={userId:77,nickname:"合成网页登录测试"};</script>'
                        mime = 'text/html; charset=utf-8'
                    else:
                        content = '<html><body><p class="suc-txt" style="display:none">扫描成功</p><iframe src="/fixture-frame"></iframe><script>window.pywebview=undefined;</script></body></html>'
                        mime = 'text/html; charset=utf-8'
                    stream = MemoryStream(Array[Byte](content.encode('utf-8')))
                    args.Response = window.native.webview.CoreWebView2.Environment.CreateWebResourceResponse(stream, 200, 'OK', 'Content-Type: ' + mime)
                def fixture_setup():
                    window.native.webview.CoreWebView2.WebResourceRequested += fixture_resource
                    return None
                window.native.Invoke(Func[Object](fixture_setup))
                def fixture_cookie():
                    manager = window.native.webview.CoreWebView2.CookieManager
                    cookie = manager.CreateCookie('MUSIC_U', 'synthetic-only', '.music.163.com', '/')
                    cookie.IsHttpOnly = True
                    cookie.IsSecure = True
                    manager.AddOrUpdateCookie(cookie)
                    return None
                window.native.Invoke(Func[Object](fixture_cookie))
            window.load_url(ORIGIN + '/#/my/')
            emit({'type': 'ready'})
            deadline = time.monotonic() + (35 if probe or flow_probe else 600)
            last_stage = None
            probe_started = 0
            probe_nonce = None
            probe_cookie = None
            login_opened = bridge_disabled = False
            last_scan = None
            account_probe = AccountProbe()
            native_retry = False
            def status(stage):
                nonlocal last_stage
                if stage != last_stage:
                    last_stage = stage
                    emit({'type':'status', 'stage':stage})
            while not closed.is_set() and time.monotonic() < deadline:
                try:
                    command = commands.get(timeout=1)
                    if command == 'close':
                        window.destroy()
                        return
                    if command == 'check':
                        probe_started = 0
                        native_retry = True
                        status('checking')
                except queue.Empty:
                    pass
                if not official_page(current_url()):
                    continue
                if test and not bridge_disabled and window.events.loaded.is_set():
                    window.run_js('window.pywebview = undefined;')
                    bridge_disabled = True
                if flow_probe and not login_opened and window.events.loaded.is_set():
                    window.run_js("document.querySelector('[data-action=login]')?.click();")
                    login_opened = True
                if probe:
                    page = window.evaluate_js('({length:document.body.innerText.length, frames:document.querySelectorAll("iframe").length, links:document.links.length})')
                    emit({'type': 'probe_status', 'page': page})
                    if isinstance(page, dict) and page.get('length', 0) > 30 and page.get('links', 0) > 3:
                        emit({'type': 'probe', 'official_page_loaded': True})
                        window.destroy()
                        return
                    continue
                state = page_state(window)
                while not site_events.empty():
                    last_scan = site_events.get_nowait()
                    status(last_scan)
                    if flow_probe:
                        emit({'type':'probe_flow', 'stage':last_scan})
                        window.destroy()
                        return
                if state.get('stage') in ('scanned', 'expired'):
                    if state['stage'] == 'expired' or last_scan not in ('confirmed', 'site_rejected'):
                        last_scan = state['stage']
                        status(last_scan)
                cookie = login_cookie(window.get_cookies())
                if 'MUSIC_U=' not in cookie:
                    probe_started = 0
                    if not state.get('stage') and last_scan not in ('scanned', 'confirmed', 'site_rejected'):
                        status('waiting')
                    continue
                fingerprint = hashlib.sha256(cookie.encode()).digest()
                candidate = state.get('profile') or {}
                profile = candidate.get('profile') if candidate.get('nonce') == probe_nonce and probe_cookie == fingerprint else None
                # Page fetch can be affected by page scripts or browser state.
                # Verify the same isolated credentials independently; never infer
                # a login from cookie presence or a stale rendered GUser alone.
                # Fixtures remain entirely offline and never send fake cookies.
                if not test and not profile:
                    profile, native_stage = account_probe.poll(cookie, native_retry)
                    native_retry = False
                    if native_stage:
                        status(native_stage)
                if not isinstance(profile, dict) or not profile.get('userId'):
                    if test and probe_started and not candidate.get('pending'):
                        status('verification_retry')
                    if not probe_started or time.monotonic() - probe_started > 10:
                        probe_nonce = str(time.monotonic_ns())
                        probe_cookie = fingerprint
                        probe_started = time.monotonic()
                        script = PROFILE_PROBE.replace('__NONCE__', json.dumps(probe_nonce))
                        script = script.replace('__FIXTURE_SECRET__', json.dumps('fixture-secret16') if test else 'null')
                        window.run_js(script)
                        if test:
                            status('credential')
                    continue
                if not official_page(current_url()):
                    continue
                # Re-read HttpOnly credentials after verification; a navigation or
                # cookie rotation must not hand off the earlier cookie snapshot.
                cookie = login_cookie(window.get_cookies())
                if hashlib.sha256(cookie.encode()).digest() != fingerprint:
                    continue
                session = session_data(dict(api='', uid=profile['userId'],
                    nickname=profile.get('nickname', ''), cookie=cookie), '')
                token = base64.b64encode(protect(json.dumps(session).encode())).decode('ascii')
                emit({'type': 'session', 'protected': token})
                window.destroy()
                return
            if not closed.is_set():
                emit({'type': 'timeout'})
                window.destroy()
        except Exception:
            # Browser exceptions can contain URLs/cookies. Never print their text.
            emit({'type': 'fatal'})
            if not closed.is_set():
                window.destroy()

    # A fresh private profile for each attempt; remember-login stays in DPAPI only.
    with tempfile.TemporaryDirectory(prefix='tianyi-netease-login-', ignore_cleanup_errors=True) as directory:
        webview.start(loop, gui='edgechromium', private_mode=True, storage_path=directory)


if __name__ == '__main__':
    try:
        run()
    except Exception:
        emit({'type': 'fatal'})
        sys.exit(1)
