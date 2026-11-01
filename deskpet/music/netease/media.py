"""Normal NetEase media results; no unlocking, alternate sources or audio IO.

freeTrialInfo marks the returned clip; freeTrialPrivilege describes eligibility
and does not itself prove that a URL is a clip. A shorter media duration than
song metadata is treated conservatively as a trial. Missing upstream flags can
never prove a complete file; downloads only use the normal download endpoint.
"""
from pathlib import PurePosixPath
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .links import music_id


EXTENSIONS = frozenset({'mp3', 'm4a', 'aac', 'flac', 'wav', 'ogg'})


def validate_media_url(url):
    """Return HTTPS for numbered NetEase audio CDN hosts; never fetch the URL.

The allowlist intentionally rejects new/unknown CDN names until verified. No
literal IPs, localhost, userinfo, fragments, nonstandard ports or file URLs.
DNS is not resolved here, so this pure check cannot override local DNS/hosts.
"""
    if not isinstance(url, str) or len(url) > 8192 or any(c.isspace() or ord(c) < 32 for c in url) or '\\' in url:
        raise ValueError('网易云音源地址无效。')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or re.fullmatch(r'm[0-9]{1,4}\.music\.126\.net', parts.hostname) is None
            or parts.username or parts.password or parts.fragment
            or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
        raise ValueError('音源不在已核对的网易云HTTPS音频CDN范围内。')
    decoded = unquote(parts.path)
    if (not decoded.startswith('/') or any(part in ('.', '..') for part in decoded.split('/'))
            or any(ord(c) < 32 or c == '\\' for c in decoded)
            or PurePosixPath(decoded).suffix.lower().lstrip('.') not in EXTENSIONS):
        raise ValueError('音源路径不是受支持的音频文件。')
    return urlunsplit(('https', parts.hostname, parts.path, parts.query, ''))


def media_info(raw, song_id, download=False, full_duration_ms=0):
    song_id = music_id(song_id)
    result = dict(id=song_id, url='', extension='', trial=False, trial_start_ms=0,
                  duration_ms=0, size=0, unavailable=True, reason='当前账号没有可用音源或接口格式已变化。')
    if not isinstance(raw, dict) or type(raw.get('code')) is not int:
        return result
    if raw['code'] != 200:
        result['reason'] = '此操作需要有效登录或相应下载权限。' if raw['code'] in (301, 401, 403) else '网易云接口未提供可用音源。'
        return result
    data = raw.get('data')
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict) and str(item.get('id')) == song_id), None)
    if not isinstance(data, dict) or str(data.get('id')) != song_id:
        return result
    if type(data.get('code', 200)) is not int or data.get('code', 200) != 200 or not data.get('url'):
        result['reason'] = '网易云未授权此曲目或曲目不可用；可在原页面查看。'
        return result
    extension = data.get('type', data.get('encodeType', ''))
    if not isinstance(extension, str) or extension.lower() not in EXTENSIONS:
        result['reason'] = '接口返回的音频格式暂不支持。'
        return result
    duration, size = data.get('time', 0), data.get('size', 0)
    if type(duration) is not int or duration < 0 or type(size) is not int or not 0 <= size <= 1024 * 1024 * 1024:
        return result
    result.update(extension=extension.lower(), duration_ms=duration or full_duration_ms, size=size)
    trial = data.get('freeTrialInfo')
    if trial is not None:
        # Do not accept the string "null" emitted by some alternate-source APIs.
        if not isinstance(trial, dict):
            result['reason'] = '接口试听标记格式不兼容，未将其当作完整音频。'
            return result
        result['trial'] = True
        start, end = trial.get('start', 0), trial.get('end', 0)
        if type(start) in (int, float) and type(end) in (int, float) and 0 <= start < end <= 86400:
            result.update(trial_start_ms=int(start * 1000), duration_ms=int((end - start) * 1000))
    if full_duration_ms > 0 and duration > 0 and duration + 2000 < full_duration_ms:
        result['trial'] = True
    if download and result['trial']:
        result['reason'] = '接口仅提供试听或截断音频，不会保存为完整版；请使用账号正常下载权限。'
        return result
    try:
        url = validate_media_url(data['url'])
    except ValueError:
        result['reason'] = '返回的音源未通过网易云CDN与文件格式校验，未使用替代音源。'
        return result
    if PurePosixPath(unquote(urlsplit(url).path)).suffix.lower() != '.' + result['extension']:
        result['reason'] = '音频扩展名与接口类型不一致。'
        return result
    result.update(url=url, unavailable=False,
                  reason='仅试听片段，歌词时间轴需加上试听起点。' if result['trial'] else
                         '正常下载接口返回，仍以账号实际权限和文件校验为准。' if download else
                         '正常播放接口返回；接口未标记试听不等同已验证会员权限。')
    return result
