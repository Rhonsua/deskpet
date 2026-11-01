"""Strict IDs and canonical links; no short-link redirects or arbitrary URLs."""
import ipaddress
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


def music_id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,18}', value) is None:
        raise ValueError('网易云ID须为1～19位正整数。')
    return value


def parse_link(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value.strip()):
        raise ValueError('请粘贴完整的网易云歌曲或歌单链接。')
    parts = urlsplit(value.strip())
    if (parts.scheme not in ('http', 'https') or parts.hostname not in ('music.163.com', 'y.music.163.com')
            or parts.username or parts.password or parts.port not in (None, 80, 443)):
        raise ValueError('只接受music.163.com的歌曲／歌单链接，不自动展开短链接。')
    path, query = parts.path.rstrip('/'), parts.query
    if parts.fragment:
        if path not in ('', '/') or query or not parts.fragment.startswith('/'):
            raise ValueError('网易云链接路径不明确。')
        fragment = urlsplit(parts.fragment)
        if fragment.fragment or fragment.scheme or fragment.netloc:
            raise ValueError('网易云链接路径不明确。')
        path, query = fragment.path.rstrip('/'), fragment.query
    if path not in ('/song', '/playlist', '/m/song', '/m/playlist'):
        raise ValueError('只支持歌曲song和歌单playlist链接。')
    values = parse_qs(query, keep_blank_values=True)
    if len(values.get('id', [])) != 1:
        raise ValueError('链接必须包含唯一的歌曲或歌单ID。')
    if any(key not in {'id', 'userid', 'uct2', 'app_version', 'sc', 'from', 'dlt', 'dl', 's', 'market'} for key in values):
        raise ValueError('链接包含无法识别的参数，请使用原始歌曲／歌单链接。')
    return path.rsplit('/', 1)[-1], music_id(values['id'][0])


def canonical_link(kind, item_id):
    if kind not in ('song', 'playlist'):
        raise ValueError('不支持的网易云链接类型。')
    return f'https://music.163.com/{kind}?id={music_id(item_id)}'


def api_base(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('社区API地址无效。')
    if not value.strip():
        return ''
    parts = urlsplit(value.strip())
    try:
        local = parts.hostname == 'localhost' or ipaddress.ip_address(parts.hostname or '').is_loopback
    except ValueError:
        local = False
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.port == 0 or (parts.scheme != 'https' and not (parts.scheme == 'http' and local))):
        raise ValueError('可信社区API须为HTTPS；本机回环服务可使用HTTP。')
    if any(c.isspace() for c in value) or '%' in parts.netloc:
        raise ValueError('社区API地址无效。')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))
