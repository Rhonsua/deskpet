"""Strict Bilibili video links and saved web-playlist data."""
import json
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


VIDEO_HOSTS = {'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'}
VIDEO_PATH = re.compile(r'^/video/(BV[0-9A-Za-z]{10}|av[1-9][0-9]*)(?:/)?$')


def video_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('请填写 B 站视频完整链接（BV 或 av）')
    value = value.strip()
    if any(ord(char) < 32 for char in value) or '\\' in value:
        raise ValueError('链接格式不正确')
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        port = parsed.port
    except ValueError as error:
        raise ValueError('链接格式不正确') from error
    match = VIDEO_PATH.fullmatch(parsed.path)
    if (parsed.scheme not in ('http', 'https') or host not in VIDEO_HOSTS or
            parsed.username or parsed.password or port not in (None, 80, 443) or not match):
        raise ValueError('只接受 bilibili.com/video/ 下的 BV / av 视频链接；短链接请先展开')
    params = parse_qs(parsed.query)
    part = params.get('p', ['1'])
    if len(part) != 1 or not part[0].isdigit() or not 1 <= int(part[0]) <= 10000:
        raise ValueError('视频分 P 参数不正确')
    query = 'p=' + str(int(part[0])) if int(part[0]) != 1 else ''
    return urlunsplit(('https', 'www.bilibili.com', '/video/' + match[1] + '/', query, ''))


def load_web_tracks(payload):
    try:
        data = json.loads(payload or '[]')
    except (ValueError, TypeError):
        return []
    result, seen = [], set()
    for item in data if isinstance(data, list) else []:
        try:
            url = video_url(item.get('url'))
        except (ValueError, AttributeError):
            continue
        if url not in seen:
            title = item.get('title', '')
            result.append({'url': url, 'title': title[:200] if isinstance(title, str) else ''})
            seen.add(url)
    return result


class EndLatch:
    """Ignore late page events and emit one completion per selected track."""
    def __init__(self):
        self.token = ''
        self.completed = False

    def reset(self, token):
        self.token, self.completed = token, False

    def accept(self, event):
        if (event.get('token') != self.token or self.completed or
                not event.get('ended') or not event.get('seen_playing')):
            return False
        self.completed = True
        return True
