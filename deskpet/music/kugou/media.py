from urllib.parse import urlsplit,unquote
from pathlib import PurePosixPath

def validate_media_url(url):
    if not isinstance(url,str) or len(url)>8192 or any(c.isspace() or ord(c)<32 for c in url) or '\\' in url: raise ValueError('音源地址无效。')
    p=urlsplit(url); h=(p.hostname or '').lower()
    if p.scheme not in ('http','https') or h not in ('fsandroid.tx.kugou.com','fsmobile.kugou.com') or p.username or p.password or p.fragment or p.port not in (None,80 if p.scheme=='http' else 443): raise ValueError('音源不在已核对的酷狗CDN范围。')
    path=unquote(p.path)
    if any(x in ('.','..') for x in path.split('/')) or PurePosixPath(path).suffix.lower() not in ('.mp3','.m4a','.aac','.flac','.ogg','.wav'): raise ValueError('音频路径无效。')
    return p._replace(scheme="https",netloc=h).geturl()

def valid_media_url(url):
    try: validate_media_url(url); return True
    except ValueError: return False
