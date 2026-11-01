"""Qt-native bounded async transport; isolated cookie jar, no redirect forwarding."""
import json
import sys
import time
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest, QSslSocket

from .service import ApiError, Request, SessionExpired


class Client(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Select Windows' native TLS before Crypto/HTTPS lazy loading: loading
        # Crypto first can make Qt's dynamic OpenSSL backend abort natively.
        # Schannel keeps the normal Windows certificate verification enabled.
        if sys.platform == 'win32':
            if 'schannel' not in QSslSocket.availableBackends() or not QSslSocket.setActiveBackend('schannel'):
                raise ApiError('Windows安全连接组件不可用，请重新安装桌宠运行环境。')
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.operation = None
        self.kind = ''
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        operation, self.operation = self.operation, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if operation is not None:
            operation.close()

    def run(self, kind, operation):
        self.cancel()
        self.kind, self.operation = kind, operation
        self.deadline = time.monotonic() + 180
        self._advance()

    def _advance(self, value=None, error=None):
        try:
            request = self.operation.throw(error) if error else self.operation.send(value)
            if not isinstance(request, Request):
                raise ApiError('网易云适配器返回了不兼容的请求。')
            self._request(request)
        except StopIteration as done:
            kind, self.operation = self.kind, None
            self.completed.emit(kind, done.value)
        except Exception as failure:
            kind = self.kind
            self.cancel()
            message = str(failure) if isinstance(failure, ApiError) else '网易云响应格式或本地数据处理失败，请重试。'
            self.failed.emit(kind, message, isinstance(failure, SessionExpired))

    def _request(self, descriptor):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ApiError('本次读取超过3分钟，请重试；未冒充完整结果。')
        self.descriptor = descriptor
        self.raw = bytearray()
        values = dict(descriptor.params)
        direct_cookie = ''
        address = descriptor.url
        if descriptor.direct:
            from .direct import prepare_request
            address, values, direct_cookie = prepare_request(descriptor.url, values, descriptor.cookie)
        if descriptor.community:
            values['timestamp'] = str(time.time_ns() // 1000000)
            if descriptor.cookie:
                values['cookie'] = descriptor.cookie
        if not descriptor.community and not descriptor.direct:
            address += '?' + urlencode(values)
        request = QNetworkRequest(QUrl(address))
        request.setRawHeader(b'Accept', b'application/json')
        request.setRawHeader(b'Referer', b'https://music.163.com/')
        request.setRawHeader(b'User-Agent', b'Mozilla/5.0' if descriptor.direct else b'DesktopPet-NeteaseMetadata/1.0')
        if direct_cookie:
            request.setRawHeader(b'Cookie', direct_cookie.encode('ascii'))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        # Do not consume a browser/system cookie jar or replay Set-Cookie headers.
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
        if descriptor.community or descriptor.direct:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/x-www-form-urlencoded')
            reply = self.manager.post(request, urlencode(values).encode())
        else:
            reply = self.manager.get(request)
        self.reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finish(reply))
        self.timer.start(max(1, min(20000, int(remaining * 1000))))

    def _read(self, reply):
        if reply is not self.reply:
            return
        self.raw.extend(bytes(reply.readAll()))
        if len(self.raw) > 8 * 1024 * 1024:
            self._request_failed(ApiError('响应超过8MiB，已停止本页读取。'))

    def _request_failed(self, error):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if self.operation is not None:
            self._advance(error=error)

    def _timeout(self):
        if self.reply is not None:
            self._request_failed(ApiError('网易云请求超过20秒，可取消后重试。'))

    def _finish(self, reply):
        if reply is not self.reply:
            return
        self._read(reply)
        if reply is not self.reply:
            return
        self.reply = None
        self.timer.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        network_error = reply.error()
        reply.deleteLater()
        try:
            if self.descriptor.cookie and status in (401, 403):
                raise SessionExpired('登录已失效或无权访问，请重新扫码。')
            if not 200 <= status < 300:
                raise ApiError(f'网易云请求失败（HTTP {status or "未连接"}）；接口不转发重定向。')
            if network_error != QNetworkReply.NetworkError.NoError:
                raise ApiError('连接中断，请重试。')
            raw = json.loads(self.raw)
            if not isinstance(raw, dict):
                raise ApiError('网易云接口没有返回JSON对象。')
            nested = raw.get('data')
            code = raw.get('code', nested.get('code') if isinstance(nested, dict) else None)
            if type(code) is not int:
                raise ApiError('网易云接口缺少状态码，请核对社区API兼容性。')
            if code == 8821:
                stage = {'qr': '生成登录二维码', 'qr_check': '确认扫码登录'}.get(self.kind, '读取网易云数据')
                raise ApiError(f'{stage}被网易云安全验证拦截（8821）。当前直连方式无法展示该验证，请稍后重试，避免连续扫码；这不表示密码错误或账号已封禁。')
            if self.descriptor.cookie and code in (301, 302, 401, 403):
                raise SessionExpired('独立登录会话过期或无权访问，请重新扫码。')
            if code not in self.descriptor.allowed:
                raise ApiError(f'网易云接口拒绝请求（状态{code}）；可能需登录、内容不可见或接口发生变化。')
            if self.descriptor.direct:
                from .direct import response_cookie, validate_url
                validate_url(reply.url().toString())
                headers = [bytes(value) for key, value in reply.rawHeaderPairs() if bytes(key).lower() == b'set-cookie']
                raw['_direct_cookie'] = response_cookie(self.descriptor.cookie, headers)
        except (ValueError, UnicodeError) as failure:
            error = failure if isinstance(failure, ApiError) else ApiError('网易云接口返回了无效JSON。')
            self._advance(error=error)
            return
        self._advance(raw)
