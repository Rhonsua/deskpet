"""Provider settings; Windows DPAPI protects remembered API keys at rest."""
import base64
import ctypes
import ipaddress
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def endpoint(value):
    parts = urlsplit(value.strip())
    try:
        local = parts.hostname == 'localhost' or ipaddress.ip_address(parts.hostname or '').is_loopback
    except ValueError:
        local = False
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or (parts.scheme != 'https' and not (parts.scheme == 'http' and local))):
        raise ValueError('请输入 HTTPS 接口地址；本机服务可以使用 http://localhost 或回环地址。')
    try:
        parts.port
    except ValueError as error:
        raise ValueError('接口地址的端口无效。') from error
    path = parts.path.rstrip('/')
    if not path:
        path = '/v1'
    if not path.endswith('/chat/completions'):
        path += '/chat/completions'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


class _Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('此系统不支持 Windows 密钥保护，请取消“在本机记住 Key”。')
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('无法使用 Windows 加密或解密 Key；请重新填写，或取消记住 Key。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


@dataclass
class ProviderConfig:
    base_url: str = ''
    model: str = ''
    api_key: str = ''
    remember_key: bool = True
    stream: bool = True

    def validate(self):
        url = endpoint(self.base_url)
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError('请填写服务商提供的模型名称（最多 200 字符）。')
        if any(c in self.api_key for c in '\r\n'):
            raise ValueError('API Key 不能包含换行。')
        return url


class ConfigFile:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return ProviderConfig(), ''
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            config = ProviderConfig(base_url=str(raw.get('base_url', '')),
                                    model=str(raw.get('model', '')),
                                    remember_key=raw.get('remember_key', True) is True,
                                    stream=raw.get('stream', True) is True)
            if raw.get('key_dpapi'):
                try:
                    config.api_key = _protect(base64.b64decode(raw['key_dpapi'], validate=True), True).decode('utf-8')
                except (ValueError, UnicodeError, OSError):
                    return config, '已读取配置，但保存的 Key 无法解密，请重新填写。'
            return config, ''
        except (ValueError, OSError, AttributeError, TypeError):
            return ProviderConfig(), '聊天配置无法读取，请重新填写并保存。'

    def save(self, config):
        config.validate()
        raw = dict(base_url=config.base_url.strip(), model=config.model.strip(),
                   remember_key=config.remember_key, stream=config.stream)
        if config.remember_key and config.api_key:
            raw['key_dpapi'] = base64.b64encode(_protect(config.api_key.encode('utf-8'))).decode('ascii')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='config-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump(raw, output, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
