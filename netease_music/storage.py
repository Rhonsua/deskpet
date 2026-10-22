"""Separate snapshots and DPAPI-only account credentials; no music-library writes."""
import base64
import ctypes
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile

from .links import api_base, music_id


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('当前系统无法使用Windows凭据保护；可仅在本次运行登录。')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows无法保护或解密网易云会话，请重新扫码。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def session_data(value, base):
    if not isinstance(base, str) or not isinstance(value, dict) or value.get('api') != base:
        raise ValueError('会话与API地址不匹配。')
    if api_base(base) != base:
        raise ValueError('会话API地址无效。')
    uid = music_id(value.get('uid'))
    cookie = value.get('cookie')
    if not isinstance(cookie, str) or not cookie or len(cookie) > 32768 or any(c in cookie for c in '\r\n\x00'):
        raise ValueError('返回的登录凭据格式不兼容。')
    if not base:
        from .direct import cookie_header, cookie_values
        cookie = cookie_header(cookie)
        if not cookie_values(cookie).get('MUSIC_U'):
            raise ValueError('直连会话没有有效登录凭据，请重新扫码。')
    nickname = value.get('nickname', '')
    if not isinstance(nickname, str) or len(nickname) > 200:
        raise ValueError('返回的用户资料格式不兼容。')
    return dict(api=base, uid=uid, cookie=cookie, nickname=nickname)


class Cache:
    def __init__(self, directory):
        self.root = Path(directory).resolve()

    def path(self, relative):
        path = self.root / relative
        path.resolve().relative_to(self.root)
        return path

    def write(self, relative, value):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='netease-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def read(self, relative):
        path = self.path(relative)
        with path.open('rb') as file:
            content = file.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError('网易云缓存文件过大。')
        return json.loads(content.decode('utf-8-sig'))

    def settings(self):
        try:
            raw = self.read('settings.json')
            return api_base(raw['api']), ''
        except FileNotFoundError:
            return '', ''
        except (OSError, ValueError, TypeError, KeyError):
            return '', '网易云接口设置无法读取，已使用公开只读模式。'

    def save_session(self, value):
        data = session_data(value, value.get('api'))
        encrypted = protect(json.dumps(data, ensure_ascii=False).encode())
        self.write('session.json', dict(version=1, dpapi=base64.b64encode(encrypted).decode('ascii')))

    def load_session(self, base):
        try:
            raw = self.read('session.json')
            if type(raw.get('version')) is not int or raw['version'] != 1:
                raise ValueError('版本无效')
            payload = protect(base64.b64decode(raw['dpapi'], validate=True), True)
            return session_data(json.loads(payload.decode()), base), ''
        except FileNotFoundError:
            return None, ''
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None, '独立登录会话无法解密或接口已变化，请重新扫码。'

    def clear_private(self):
        # Never enumerate or remove anything outside this dedicated cache root.
        self.path('session.json').unlink(missing_ok=True)
        path = self.path('private')
        if path.exists():
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('个人缓存目录是链接，不能自动清理。')
            shutil.rmtree(path)

    def save_snapshot(self, kind, item_id, data, private=False):
        if kind not in ('song', 'playlist', 'collections', 'likes'):
            raise ValueError('无效缓存类型。')
        item_id = music_id(item_id)
        previous = self.snapshot(kind, item_id, private)
        if previous and isinstance(previous.get('data'), dict):
            old = previous['data']
            if (kind in ('playlist', 'likes', 'collections') and old.get('complete') is True and data.get('complete') is not True
                    or kind == 'song' and old.get('lrc') and '失败' in data.get('lrc_status', '')):
                return False
        self.write(f'{"private" if private else "public"}/{kind}-{item_id}.json',
                   dict(version=1, fetched_at=datetime.now().isoformat(), kind=kind, id=item_id, data=data))
        return True

    def snapshot(self, kind, item_id, private=False, fresh=False):
        if kind not in ('song', 'playlist', 'collections', 'likes'):
            return None
        try:
            raw = self.read(f'{"private" if private else "public"}/{kind}-{music_id(item_id)}.json')
            if raw['version'] != 1 or raw['kind'] != kind or raw['id'] != str(item_id):
                return None
            if fresh and datetime.now() - datetime.fromisoformat(raw['fetched_at']) > timedelta(hours=24):
                return None
            return raw
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def snapshots(self, private=False):
        directory = self.path('private' if private else 'public')
        if not directory.exists():
            return []
        found = []
        for path in sorted(directory.glob('playlist-*.json'))[:200]:
            item_id = path.stem.removeprefix('playlist-')
            try:
                cached = self.snapshot('playlist', item_id, private)
                if cached:
                    found.append(cached)
            except ValueError:
                continue
        return found
