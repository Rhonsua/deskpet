"""One cancellable POST through Windows' own curl, using a private config pipe."""
import ctypes
import os
from pathlib import Path
import subprocess
import threading

from PySide6.QtCore import QObject, Signal


def system_curl():
    if os.name != 'nt':
        raise ValueError('系统 curl 连接方式仅适用于 Windows。')
    path = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(path, len(path))
    if 0 < length < len(path):
        executable = Path(path.value) / 'curl.exe'
        if executable.is_file():
            return str(executable)
    raise ValueError('未找到 Windows 自带的 curl.exe，请在 API 设置里改选默认连接。')


def config_line(name, value):
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('连接参数含有无效控制字符。')
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'{name} = "{escaped}"\n'


class CurlRequest(QObject):
    headers = Signal(int, str, int)
    body = Signal(bytes)
    ended = Signal(str)
    cleaned = Signal()
    arguments = ('--disable', '--proto', '=https,http', '--no-location', '--globoff',
                 '--silent', '--no-buffer', '--include', '--suppress-connect-headers',
                 '--max-time', '90', '--config', '-')

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.process = None
        self.cancelled = threading.Event()
        self.cleaned.connect(self.deleteLater)

    def post(self, url, key, data):
        # Curl unescapes its config exactly once. Keep all variable fields off
        # its command line, including headers, endpoint and conversation text.
        config = config_line('url', url)
        config += config_line('header', 'Accept: text/event-stream, application/json')
        config += config_line('header', 'Content-Type: application/json')
        if key:
            config += config_line('header', 'Authorization: Bearer ' + key)
        config += config_line('data-binary', data.decode('utf-8'))
        self.program = system_curl()
        threading.Thread(target=self._run, args=(config.encode('utf-8'),), daemon=True).start()

    def _read_response(self, stream):
        size = 0
        while not self.cancelled.is_set():
            line = stream.readline(65537)
            if not line:
                return
            try:
                version, code, *_ = line.split()
                if not version.startswith(b'HTTP/'):
                    raise ValueError()
                status = int(code)
            except ValueError:
                raise ValueError('无法识别 curl 返回的 HTTP 响应头。') from None
            fields = {}
            while line:
                size += len(line)
                if size > 65536:
                    raise ValueError('HTTP 响应头过大。')
                line = stream.readline(65537)
                if line in (b'\r\n', b'\n'):
                    break
                name, _, value = line.partition(b':')
                fields[name.lower()] = value.strip()
            if status >= 200:
                length = fields.get(b'content-length', b'')
                declared = (int(length) if length.isdigit() and len(length) <= 9
                            and b'transfer-encoding' not in fields else -1)
                self.headers.emit(status, fields.get(b'content-type', b'').decode('ascii','replace'), declared)
                break
        received = 0
        while not self.cancelled.is_set():
            chunk = stream.read1(32768)
            if not chunk:
                break
            received += len(chunk)
            if received > 2 * 1024 * 1024:
                raise ValueError('响应过大，已停止接收。')
            self.body.emit(chunk)

    def _run(self, config):
        process = None
        message = ''
        try:
            with self.lock:
                if self.cancelled.is_set():
                    return
                process = subprocess.Popen([self.program, *self.arguments], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                self.process = process
            with process.stdin:
                process.stdin.write(config)
            with process.stdout:
                self._read_response(process.stdout)
            code = process.wait()
            if code:
                descriptions = {5:'无法解析代理地址', 6:'无法解析接口域名', 7:'无法建立连接',
                                28:'连接超时', 35:'TLS 握手失败', 60:'证书验证失败'}
                message = f'系统 curl 错误 {code}（{descriptions.get(code, "传输失败")}）。'
        except ValueError as error:
            message = str(error)
        except OSError:
            message = '系统 curl 无法启动或连接已中断。'
        finally:
            with self.lock:
                self.process = None
                if process and process.poll() is None:
                    process.kill()
            if process:
                process.stdout.close()
                process.stdin.close()
                process.wait()
            if not self.cancelled.is_set():
                self.ended.emit(message)
            self.cleaned.emit()

    def abort(self):
        self.cancelled.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.kill()
