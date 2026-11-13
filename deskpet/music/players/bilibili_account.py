"""Reuse this app's WebPlayer account, without inspecting other browser profiles."""
import base64
import time

from deskpet.music.netease.storage import protect

COOKIE_NAMES = {'SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', 'buvid3', 'buvid4', 'b_nut', 'bili_ticket'}


def cookie_header(rows):
    values = {}
    for name, value, domain in rows:
        if (name in COOKIE_NAMES and domain.lower().lstrip('.') in ('bilibili.com', 'api.bilibili.com')
                and not any(c in value for c in '\r\n;\0')):
            values[name] = value
    return '; '.join(f'{name}={value}' for name, value in values.items()) if values.get('SESSDATA') else ''


def decode_cookie(encoded):
    if not isinstance(encoded, str) or len(encoded) > 100000:
        raise ValueError('无法接回 B站登录状态。')
    cookie = protect(base64.b64decode(encoded, validate=True), decrypt=True).decode('utf-8')
    if not cookie or len(cookie) > 32768 or any(c in cookie for c in '\r\n\0'):
        raise ValueError('无法接回 B站登录状态。')
    return cookie


def native_cookie(window):
    from System import Func, Object
    task = window.native.Invoke(Func[Object](lambda:
        window.native.webview.CoreWebView2.CookieManager.GetCookiesAsync('https://api.bilibili.com/')))
    cookies = task.GetAwaiter().GetResult()
    # WebView2 cookie properties are COM objects bound to the browser UI thread.
    # An empty cookie list hides this requirement, so parse nonempty lists there too.
    return window.native.Invoke(Func[Object](lambda:
        cookie_header((str(c.Name), str(c.Value), str(c.Domain)) for c in cookies)))


class AccountBridge:
    """Runs on the existing browser worker, independent of video state/position."""
    def __init__(self, window, webview, emit):
        self.window, self.webview, self.emit = window, webview, emit
        self.request_id = ''
        self.popup = None
        self.baseline = ''
        self.next_poll = self.deadline = 0

    def reply(self, cookie='', error=''):
        event = dict(type='import-account', request=self.request_id, error=error)
        if cookie:
            event['protected'] = base64.b64encode(protect(cookie.encode())).decode('ascii')
        else:
            event['login_required'] = not error
        self.emit(event)
        self.request_id = ''

    def request(self, request_id, login=False):
        self.request_id = request_id
        try:
            cookie = native_cookie(self.window)
            if not login:
                self.reply(cookie)
                return
            self.baseline = cookie
            self.deadline = time.monotonic() + 600
            self.next_poll = 0
            if self.popup is not None:
                self.popup.show()
                self.popup.restore()
            else:
                self.popup = self.webview.create_window('天依 · B站网页登录', 'https://passport.bilibili.com/login',
                                                       width=980, height=720, min_size=(640, 480))
                self.popup.events.closed += self.popup_closed
        except Exception:
            self.reply(error='未能读取 B站网页的登录状态，请关闭播放网页后重试。')

    def popup_closed(self):
        self.popup = None

    def cancel(self, request_id):
        if request_id == self.request_id:
            self.request_id = ''

    def poll(self):
        if not self.request_id or time.monotonic() < self.next_poll:
            return
        self.next_poll = time.monotonic() + 2
        try:
            cookie = native_cookie(self.window)
            if cookie and cookie != self.baseline:
                self.reply(cookie)
                if self.popup is not None:
                    popup, self.popup = self.popup, None
                    popup.destroy()
            elif time.monotonic() > self.deadline:
                self.reply(error='登录等待超时。登录完成后可点击“我的收藏夹”重新读取。')
            elif self.popup is None:
                self.reply(error='登录窗口已关闭；登录完成后可点击“我的收藏夹”重新读取。')
        except Exception:
            if time.monotonic() > self.deadline:
                self.reply(error='未能接回网页登录结果，请重新读取。')

    def close(self):
        self.request_id = ''
        if self.popup is not None:
            popup, self.popup = self.popup, None
            popup.destroy()
