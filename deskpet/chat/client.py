"""Qt asynchronous HTTP; abortable requests with no background worker lifetime risks."""
import json

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .protocol import SSEParser, ProtocolError, content_from_json, request_payload
from .curl_request import CurlRequest


def http_error(status):
    reasons = {400:'请求格式或模型能力不匹配；发送图片时请确认模型支持看图',
               401:'Key 无效或已过期', 402:'账户余额不足或需要付费，请检查服务商余额及套餐对应的地址和 Key',
               403:'没有访问权限', 404:'接口路径或模型不存在',
               429:'请求过于频繁或额度不足'}
    hint = reasons.get(status, '接口重定向，请填写最终地址' if 300 <= status < 400
                       else '服务拒绝请求，请检查接口地址、模型和服务状态')
    return f'连接失败（HTTP {status}）：{hint}。'


class ChatClient(QObject):
    partial = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = None
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.status = 0
        self.total_bytes = 0

    def start(self, config, messages, test=False):
        url = config.validate()
        self.cancel()
        self.text = ''
        self.raw = bytearray()
        self.total_bytes = 0
        self.parser = SSEParser()
        self.is_stream = False
        self.status = 0
        self.expected_size = -1
        payload = request_payload(url, config.model, messages, config.stream, test)
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.timer.start(90000)
        if config.transport == 'curl':
            reply = CurlRequest()
            self.reply = reply
            queued = Qt.ConnectionType.QueuedConnection
            reply.headers.connect(lambda status, content, length: self._headers(reply, status, content, length), queued)
            reply.body.connect(lambda chunk: self._consume(reply, chunk), queued)
            reply.ended.connect(lambda error: self._end(reply, error), queued)
            try:
                reply.post(url, config.api_key, data)
            except ValueError as error:
                self._fail(str(error))
                reply.deleteLater()
            return
        if self.manager is None:
            self.manager = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setRawHeader(b'Accept', b'text/event-stream, application/json')
        if config.api_key:
            request.setRawHeader(b'Authorization', ('Bearer ' + config.api_key).encode('utf-8'))
        # Never forward a user's key through a redirect to another endpoint.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        reply = self.manager.post(request, data)
        self.reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finish(reply))
        reply.metaDataChanged.connect(lambda: self._qt_headers(reply))

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            if not isinstance(reply, CurlRequest):
                reply.deleteLater()

    def _timeout(self):
        stage = (f'已收到 HTTP {self.status}，已读 {self.total_bytes} 字节，等待完整回复'
                 if self.status else '仍在等待服务返回 HTTP 响应头')
        self._fail(f'请求超过 90 秒：{stage}。')

    def _fail(self, message):
        if self.reply is not None:
            self.cancel()
            self.failed.emit(message)

    def _headers(self, reply, status, content_type, length):
        if reply is not self.reply:
            return
        if status and not 200 <= status < 300:
            self._fail(http_error(status))
            return
        self.status = status
        self.is_stream = 'text/event-stream' in content_type.lower()
        self.expected_size = length

    def _qt_headers(self, reply):
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        length = bytes(reply.rawHeader('Content-Length'))
        size = (int(length) if length.isdigit() and len(length) <= 9
                and not reply.hasRawHeader('Content-Encoding')
                and not reply.hasRawHeader('Transfer-Encoding') else -1)
        self._headers(reply, status, str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or ''), size)

    def _read(self, reply):
        if reply is not self.reply:
            return
        self._qt_headers(reply)
        if reply is self.reply:
            self._consume(reply, bytes(reply.readAll()))

    def _consume(self, reply, chunk):
        if reply is not self.reply or not chunk:
            return
        self.total_bytes += len(chunk)
        if self.total_bytes > 2 * 1024 * 1024:
            self._fail('响应过大，已停止接收。')
            return
        try:
            if self.is_stream:
                self.text += self.parser.feed(chunk)
                if len(self.text) > 16000:
                    raise ProtocolError('回复超过长度限制，请缩短问题或调整模型。')
                self.partial.emit(self.text)
            else:
                self.raw.extend(chunk)
        except ProtocolError as error:
            self._fail(str(error))
            return
        if self.status and (self.parser.done or self.total_bytes == self.expected_size):
            self._end(reply, '')

    def _finish(self, reply):
        if reply is not self.reply:
            return
        self._read(reply)
        if reply is not self.reply:
            return
        error = reply.error()
        # Qt error strings may contain URLs or provider-controlled text.
        detail = '' if error == QNetworkReply.NetworkError.NoError else f'Qt 网络错误 {error.name}。'
        self._end(reply, detail)

    def _end(self, reply, error):
        if reply is not self.reply:
            return
        self.cancel()
        if not error and not self.parser.done and self.expected_size >= 0 and self.total_bytes != self.expected_size:
            error = 'HTTP 正文未完整接收。'
        if error or not self.status:
            status = f'HTTP {self.status}，已读 {self.total_bytes} 字节' if self.status else '尚未收到 HTTP 响应头'
            self.failed.emit(f'连接失败（{status}）。{error}')
            return
        try:
            if self.is_stream:
                self.text += self.parser.feed(b'', final=True)
                if not self.parser.done:
                    raise ProtocolError('流式回复未完整结束，未保存到上下文，请重试。')
                text = self.text
            else:
                text = content_from_json(json.loads(self.raw))
            if not text.strip():
                raise ProtocolError('模型没有返回可显示的文字，请检查模型或改用非流式模式。')
            if len(text) > 16000:
                raise ProtocolError('回复超过长度限制，未保存。')
        except (ValueError, UnicodeError) as error:
            self.failed.emit(str(error) if isinstance(error, ProtocolError) else '响应不是兼容的 JSON 文本格式。')
            return
        self.completed.emit(text)
