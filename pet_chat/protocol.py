"""Bounded incremental SSE parser, independent of Qt for protocol tests."""
import json
from urllib.parse import urlsplit


def request_payload(url, model, messages, stream=True, test=False):
    model = model.strip()
    payload = dict(model=model, messages=messages, stream=stream and not test,
                   max_tokens=32 if test else 768)
    # Official Flash defaults to thinking, which can consume the entire small
    # desktop-chat/test output budget before returning any visible content.
    if urlsplit(url).hostname == 'api.deepseek.com' and model == 'deepseek-flash':
        payload['thinking'] = {'type': 'disabled'}
    return payload


class ProtocolError(ValueError):
    pass


def content_from_json(data, streaming=False):
    if not isinstance(data, dict) or data.get('error'):
        raise ProtocolError('模型服务返回了错误，请检查模型名称、额度和接口设置。')
    choices = data.get('choices')
    if choices == []:
        return ''
    try:
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise TypeError()
        message = choices[0].get('delta' if streaming else 'message')
        if not isinstance(message, dict):
            raise TypeError()
        content = message.get('content')
        if content is None:
            return ''
        if not isinstance(content, str):
            raise TypeError()
        return content
    except (AttributeError, IndexError, TypeError) as error:
        raise ProtocolError('接口返回格式不兼容，需要 Chat Completions 文本接口。') from error


class SSEParser:
    def __init__(self):
        self.buffer = b''
        self.data = []
        self.done = False
        self.data_bytes = 0

    def feed(self, chunk, final=False):
        self.buffer += chunk
        if len(self.buffer) > 1024 * 1024:
            raise ProtocolError('单个响应片段过大，已停止接收。')
        output = []
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            self._line(line.rstrip(b'\r'), output)
        if final:
            if self.buffer:
                self._line(self.buffer.rstrip(b'\r'), output)
                self.buffer = b''
            self._line(b'', output)
        return ''.join(output)

    def _line(self, line, output):
        if self.done:
            return
        if line == b'':
            if not self.data:
                return
            value = b'\n'.join(self.data).strip()
            self.data = []
            self.data_bytes = 0
            if value == b'[DONE]':
                self.done = True
                return
            try:
                output.append(content_from_json(json.loads(value), streaming=True))
            except (ValueError, UnicodeError) as error:
                if isinstance(error, ProtocolError):
                    raise
                raise ProtocolError('流式响应格式不兼容，可关闭“流式显示”后再试。') from error
        elif line.startswith(b'data:'):
            self.data_bytes += len(line) + 1
            if self.data_bytes > 1024 * 1024:
                raise ProtocolError('单个响应片段过大，已停止接收。')
            self.data.append(line[5:].lstrip(b' '))
