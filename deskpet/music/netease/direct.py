"""Small allowlisted adapter for NetEase's own HTTPS JSON endpoints.

Anonymous probes on 2026-10-22 verified normal WEAPI QR key (200), QR
waiting (801), logged-out profile (200) and raw v6 public playlist IDs (200).
The paths are informed by the api-enhanced project's module implementations;
these private site interfaces are not a guaranteed official developer API.
No proxy, Node process, browser cookie store or remote code is used.
"""
from http.cookies import CookieError, SimpleCookie
import base64
import json
import re
import secrets
from urllib.parse import urlsplit


ORIGIN = 'https://music.163.com'
WEAPI_ROUTES = {
    '/api/login/qrcode/unikey': '/weapi/login/qrcode/unikey',
    '/api/login/qrcode/client/login': '/weapi/login/qrcode/client/login',
    '/api/w/nuser/account/get': '/weapi/w/nuser/account/get',
}
PATHS = frozenset({
    '/api/login/qrcode/unikey', '/api/login/qrcode/client/login',
    '/api/w/nuser/account/get', '/api/user/playlist', '/api/song/like/get',
    '/api/v6/playlist/detail', '/api/song/detail', '/api/song/lyric',
    '/api/song/enhance/player/url', '/api/song/enhance/download/url',
}) | frozenset(WEAPI_ROUTES.values())
COOKIE_NAMES = frozenset({'MUSIC_U', 'MUSIC_A', '__csrf', '__remember_me', 'NMTID'})


def validate_url(url):
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname != 'music.163.com' or parts.port not in (None, 443)
            or parts.username or parts.password or parts.query or parts.fragment or parts.path not in PATHS):
        raise ValueError('直连请求仅允许网易云HTTPS固定接口。')
    return url


def _valid_value(value):
    return (isinstance(value, str) and len(value) <= 16384
            and all(0x21 <= ord(char) <= 0x7e and char not in '\\",;' for char in value))


def cookie_values(cookie):
    if not isinstance(cookie, str) or len(cookie) > 32768 or any(char in cookie for char in '\r\n\x00'):
        raise ValueError('直连会话凭据格式无效。')
    result = {}
    for segment in cookie.split(';'):
        name, separator, value = segment.strip().partition('=')
        if separator and name in COOKIE_NAMES:
            if not _valid_value(value):
                raise ValueError('直连会话凭据格式无效。')
            if value:
                result[name] = value
    return result


def cookie_header(cookie):
    values = cookie_values(cookie)
    return '; '.join(f'{name}={value}' for name, value in sorted(values.items()))


def request_values(url, params, cookie):
    validate_url(url)
    values = dict(params)
    cookies = cookie_values(cookie)
    values['csrf_token'] = cookies.get('__csrf', '')
    return values, cookie_header(cookie)


_PUBLIC_KEY = '''-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDgtQn2JZ34ZC28NWYpAUd98iZ37BUrX/aKzmFbt7clFSs6sXqHauqKWqdtLkF2KexO40H1YTX8z2lSgBBOAxLsvaklV8k4cBFK9snQXE9/DDaFt6Rr7iVZMldczhC0JNgTz+SHXT6CBHuX3e9SdB1Ua44oncaTWz7OBGLbCiK45wIDAQAB
-----END PUBLIC KEY-----'''


def encode_weapi(values):
    """Normal web request framing; no permission or verification bypass."""
    try:
        from Crypto.Cipher import AES
        from Crypto.PublicKey import RSA
        from Crypto.Util.Padding import pad
    except ImportError as error:
        from .service import ApiError
        raise ApiError('缺少网易云登录所需的加密组件，请重新运行启动脚本安装依赖。') from error
    secret = ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(16)).encode('ascii')
    def encrypt(data, key):
        return base64.b64encode(AES.new(key, AES.MODE_CBC, b'0102030405060708').encrypt(pad(data, 16)))
    plain = json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    encrypted = encrypt(encrypt(plain, b'0CoJUm6Qyw8W8jud'), secret).decode('ascii')
    public = RSA.import_key(_PUBLIC_KEY)
    wrapped = pow(int.from_bytes(secret[::-1], 'big'), public.e, public.n)
    return dict(params=encrypted, encSecKey=f'{wrapped:0256x}')


def prepare_request(url, params, cookie):
    """Keep Service descriptors stable; migrate only login wire requests."""
    values, header = request_values(url, params, cookie)
    path = urlsplit(url).path
    target = WEAPI_ROUTES.get(path, path)
    if target in WEAPI_ROUTES.values():
        # Web QR key and check must share type=1 (go-musicfox QR client).
        if '/login/qrcode/' in target:
            values['type'] = 1
        values = encode_weapi(values)
    return ORIGIN + target, values, header


def response_cookie(previous, headers):
    """Consume only known cookie names from fixed-origin Set-Cookie headers."""
    values = cookie_values(previous)
    for header in headers:
        try:
            if isinstance(header, bytes):
                header = header.decode('ascii')
            if not isinstance(header, str) or len(header) > 32768 or any(c in header for c in '\r\n\x00'):
                continue
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                if name not in COOKIE_NAMES:
                    continue
                domain = morsel['domain'].lower().lstrip('.')
                if domain not in ('', 'music.163.com', '163.com') or morsel['path'] not in ('', '/'):
                    continue
                if not _valid_value(morsel.value):
                    continue
                if not morsel.value or morsel['max-age'] == '0':
                    values.pop(name, None)
                else:
                    values[name] = morsel.value
        except (CookieError, ValueError, UnicodeError):
            continue
    result = '; '.join(f'{name}={value}' for name, value in sorted(values.items()))
    if len(result) > 32768:
        raise ValueError('网易云返回的会话凭据超过限制。')
    return result


def qr_url(key):
    # No fetched images or third-party QR service: the host renders this URL
    # locally with qrcode.get_matrix and Qt.
    if not isinstance(key, str) or re.fullmatch(r'[a-zA-Z0-9_-]{8,512}', key) is None:
        raise ValueError('网易云返回的扫码key格式不兼容。')
    return ORIGIN + '/login?codekey=' + key
