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
                raise ApiError('酷狗适配器返回了不兼容的请求。')
            self._request(request)
        except StopIteration as done:
            kind, self.operation = self.kind, None
            self.completed.emit(kind, done.value)
        except Exception as failure:
            kind = self.kind
            self.cancel()
            message = str(failure) if isinstance(failure, ApiError) else '酷狗响应格式或本地数据处理失败，请重试。'
            self.failed.emit(kind, message, isinstance(failure, SessionExpired))

    def _request(self, descriptor):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ApiError('本次读取超过3分钟，请重试；未冒充完整结果。')
        self.descriptor = descriptor
        self.raw = bytearray()
        address = descriptor.url + ('?' + urlencode(descriptor.params) if descriptor.params else '')
        if descriptor.redirect_probe:
            from .links import safe_share_url
            safe_share_url(address)
        request = QNetworkRequest(QUrl(address))
        request.setRawHeader(b'Accept', b'application/json')
        request.setRawHeader(b'User-Agent', b'Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi')
        for key, value in descriptor.headers.items():
            request.setRawHeader(key.encode(), str(value).encode())
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
        if descriptor.body:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
            reply = self.manager.post(request, descriptor.body.encode('utf-8'))
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
            self._request_failed(ApiError('酷狗请求超过20秒，可取消后重试。'))

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
            if self.descriptor.redirect_probe:
                if status not in (301, 302, 303, 307, 308): raise ApiError('分享链接未返回官方重定向。')
                location=reply.header(QNetworkRequest.KnownHeaders.LocationHeader)
                if not location: raise ApiError('分享链接缺少跳转地址。')
                self._advance({'location': location.toString()})
                return
            if status == 401:
                raise SessionExpired('登录已失效或无权访问，请重新扫码。')
            if status == 403:
                raise ApiError('酷狗暂未允许此次请求，请检查曲目权限或稍后再试。')
            if not 200 <= status < 300:
                raise ApiError(f'酷狗请求失败（HTTP {status or "未连接"}）；接口不转发重定向。')
            if network_error != QNetworkReply.NetworkError.NoError:
                raise ApiError('连接中断，请重试。')
            raw = json.loads(self.raw)
            if not isinstance(raw, dict):
                raise ApiError('酷狗接口没有返回JSON对象。')
            if raw.get('status') == 0 or raw.get('error_code') not in (None, 0):
                code=raw.get('error_code')
                suffix=f'（错误码 {code}）' if type(code) is int else ''
                raise ApiError('酷狗接口拒绝请求或需要安全验证'+suffix+'，请稍后重试。')
        except (ValueError, UnicodeError) as failure:
            error = failure if isinstance(failure, ApiError) else ApiError('酷狗接口返回了无效JSON。')
            self._advance(error=error)
            return
        self._advance(raw)
