"""Qt asynchronous HTTP; abortable requests with no background worker lifetime risks."""
import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .protocol import SSEParser, ProtocolError, content_from_json, request_payload


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
        self.timer.timeout.connect(lambda: self._fail('请求超过 90 秒，请稍后重试或更换模型。'))

    def start(self, config, messages, test=False):
        url = config.validate()
        self.cancel()
        if self.manager is None:
            self.manager = QNetworkAccessManager(self)
        self.text = ''
        self.raw = b''
        self.total_bytes = 0
        self.parser = SSEParser()
        self.is_stream = None
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        request.setRawHeader(b'Accept', b'text/event-stream, application/json')
        if config.api_key:
            request.setRawHeader(b'Authorization', ('Bearer ' + config.api_key).encode('utf-8'))
        # Never forward a user's key through a redirect to another endpoint.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        payload = request_payload(url, config.model, messages, config.stream, test)
        reply = self.manager.post(request, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        self.reply = reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finish(reply))
        self.timer.start(90000)

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _fail(self, message):
        if self.reply is not None:
            self.cancel()
            self.failed.emit(message)

    def _read(self, reply):
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and not 200 <= status < 300:
            reply.readAll()
            return
        chunk = bytes(reply.readAll())
        self.total_bytes += len(chunk)
        if self.total_bytes > 2 * 1024 * 1024:
            self._fail('响应过大，已停止接收。')
            return
        if self.is_stream is None:
            content_type = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '')
            self.is_stream = 'text/event-stream' in content_type.lower()
        try:
            if self.is_stream:
                self.text += self.parser.feed(chunk)
                if len(self.text) > 16000:
                    raise ProtocolError('回复超过长度限制，请缩短问题或调整模型。')
                self.partial.emit(self.text)
            else:
                self.raw += chunk
        except ProtocolError as error:
            self._fail(str(error))

    def _finish(self, reply):
        if reply is not self.reply:
            return
        self._read(reply)
        if reply is not self.reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        error = reply.error()
        self.reply = None
        self.timer.stop()
        reply.deleteLater()
        if not 200 <= status < 300:
            explanations = {401: 'Key 无效或已过期', 403: '没有访问权限', 404: '接口路径或模型不存在',
                            429: '请求过于频繁或额度不足'}
            hint = explanations.get(status, '接口重定向，请填写最终地址' if 300 <= status < 400 else '服务不可用，请检查网络和接口地址')
            self.failed.emit(f'连接失败（HTTP {status or "未连接"}）：{hint}。')
            return
        if error != QNetworkReply.NetworkError.NoError:
            self.failed.emit('连接中断，回复未保存。可以重新发送。')
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
