import re
from urllib.parse import urlsplit, parse_qs

def extract_url(value):
    match=re.search(r'https://[^\s<>"\u3000]+',str(value))
    if not match: raise ValueError('请输入酷狗 HTTPS 分享链接。')
    return match.group(0).rstrip('，。！？、)]）】')

def safe_share_url(value):
    try:
        p=urlsplit(value); host=(p.hostname or '').lower()
        if (p.scheme!='https' or not (host=='kugou.com' or host.endswith('.kugou.com')) or p.username or p.password or p.port not in (None,443) or p.fragment or len(value)>8192 or any(ord(c)<32 or c.isspace() for c in value) or '\\' in value): raise ValueError()
        return value
    except ValueError: raise ValueError('分享链接必须使用酷狗官方 HTTPS 地址。')

def playlist_id(value):
    value=str(value).strip()
    if re.fullmatch(r'collection_[A-Za-z0-9_-]{1,110}',value): return value
    if re.fullmatch(r'user_\d{1,20}_[01]',value): return value
    url=safe_share_url(extract_url(value)); p=urlsplit(url); q=parse_qs(p.query)
    for key in ('global_collection_id','global_specialid'):
        candidate=(q.get(key) or [''])[0]
        if re.fullmatch(r'collection_[A-Za-z0-9_-]{1,110}',candidate): return candidate
    raise ValueError('分享链接尚需解析，或旧版数字歌单不受支持。')
