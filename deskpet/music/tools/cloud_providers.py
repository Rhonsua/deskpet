"""Small provider boundary shared by cloud playback and explicit downloads."""
import re


def provider_name(provider):
    if provider not in ('netease', 'kugou'):
        raise ValueError('不支持的音乐平台')
    return {'netease': '网易云', 'kugou': '酷狗'}[provider]


def client_class(provider):
    provider_name(provider)
    if provider == 'kugou':
        from deskpet.music.kugou.client import Client
    else:
        from deskpet.music.netease.client import Client
    return Client


def media_validator(provider):
    provider_name(provider)
    if provider == 'kugou':
        from deskpet.music.kugou.media import validate_media_url
    else:
        from deskpet.music.netease.media import validate_media_url
    return validate_media_url


def clean_tracks(tracks, provider='netease'):
    provider_name(provider)
    if provider == 'netease':
        from deskpet.music.netease.playback import clean_tracks as clean
        return clean(tracks)
    result, seen = [], set()
    for track in list(tracks)[:20000]:
        item_id = str(track.get('hash') or track.get('id', '')).upper()
        if not re.fullmatch(r'[0-9A-F]{32}', item_id):
            raise ValueError('酷狗歌曲编号无效')
        if item_id in seen:
            continue
        seen.add(item_id)
        item = dict(track)
        item.update(id=item_id, hash=item_id,
                    title=str(track.get('title', item_id))[:1000],
                    artists=str(track.get('artists', ''))[:1000])
        result.append(item)
    return result


def track_argument(item, provider='netease'):
    provider_name(provider)
    return dict(item) if provider == 'kugou' else item['id']


def service_errors(provider):
    provider_name(provider)
    if provider == 'kugou':
        from deskpet.music.kugou.service import ApiError, SessionExpired
    else:
        from deskpet.music.netease.service import ApiError, SessionExpired
    return ApiError, SessionExpired
