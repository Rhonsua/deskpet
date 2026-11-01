"""Generator-based endpoint adapter. Only its Request values perform network IO."""
from dataclasses import dataclass, field
import json

from .links import api_base, music_id
from .storage import session_data


class ApiError(ValueError):
    pass


class SessionExpired(ApiError):
    pass


@dataclass(frozen=True)
class Request:
    url: str
    params: dict
    cookie: str = field(default='', repr=False)
    community: bool = False
    allowed: tuple = (200,)
    direct: bool = False


def song_info(raw):
    if not isinstance(raw, dict):
        raise ApiError('歌曲信息字段不兼容。')
    item_id = music_id(raw.get('id'))
    title = raw.get('name')
    if not isinstance(title, str) or not title.strip() or len(title) > 1000:
        raise ApiError('歌曲标题字段不兼容。')
    artists = raw.get('ar', raw.get('artists', []))
    if not isinstance(artists, list):
        raise ApiError('歌手字段不兼容。')
    names = [item['name'][:200] for item in artists[:20]
             if isinstance(item, dict) and isinstance(item.get('name'), str)]
    duration = raw.get('dt', raw.get('duration', 0))
    return dict(id=item_id, title=title, artists=' / '.join(names),
                duration=duration if type(duration) is int and duration >= 0 else 0, unavailable=False)


def lrc_info(raw):
    if raw.get('nolyric') is True:
        return '', '纯音乐／接口标记无歌词'
    value = raw.get('lrc')
    if value is None:
        return '', '未返回逐句LRC'
    if not isinstance(value, dict) or not isinstance(value.get('lyric', ''), str):
        raise ApiError('歌词字段不兼容。')
    lyric = value.get('lyric', '')
    if len(lyric) > 256000:
        raise ApiError('歌词超过长度限制。')
    import re
    if not re.search(r'\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]', lyric):
        return '', '没有可用逐句时间轴'
    return lyric, '逐句LRC可用（未验证逐字时间轴）'


class Service:
    def __init__(self, base='', session=None, progress=lambda value: None):
        self.base = api_base(base)
        self.session = session_data(session, self.base) if session else None
        self.progress = progress

    def request(self, path, params=None, authenticated=True, cookie=None, allowed=(200,)):
        values = dict(params or {})
        credential = cookie if cookie is not None else (self.session['cookie'] if self.session and authenticated else '')
        if self.base:
            return Request(self.base + path, values, credential, True, allowed)
        from .direct import ORIGIN
        paths = {'/song/detail': '/api/song/detail', '/lyric': '/api/song/lyric',
                 '/playlist/detail': '/api/v6/playlist/detail', '/user/playlist': '/api/user/playlist',
                 '/likelist': '/api/song/like/get', '/login/status': '/api/w/nuser/account/get',
                 '/login/qr/key': '/api/login/qrcode/unikey',
                 '/login/qr/check': '/api/login/qrcode/client/login',
                 '/song/url': '/api/song/enhance/player/url',
                 '/song/download/url': '/api/song/enhance/download/url'}
        if path not in paths:
            raise ApiError('网易云直连接口不支持此操作。')
        if path == '/song/detail':
            ids = values.pop('ids').split(',')
            values.update(ids=json.dumps([int(item) for item in ids]), id=ids[0])
        elif path == '/lyric':
            values.update(lv=-1, kv=-1, tv=-1)
        elif path == '/playlist/detail':
            values['n'] = 100000
        elif path in ('/login/qr/key', '/login/qr/check'):
            values['type'] = 3
        elif path == '/user/playlist':
            values['includeVideo'] = 'true'
        elif path == '/song/url':
            values['ids'] = json.dumps([int(music_id(values.pop('id')))])
        return Request(ORIGIN + paths[path], values, credential, False, allowed, True)

    def media(self, song_id, download=False):
        """Resolve only normal account-authorized endpoints; never fetch audio."""
        from .media import media_info
        song_id = music_id(song_id)
        if type(download) is not bool:
            raise ApiError('download须为布尔值。')
        path = '/song/download/url' if download else '/song/url'
        permission_failure = False
        try:
            raw = yield self.request(path, dict(id=song_id, br=128000), allowed=(200, 301, 403, 404, 406, 451))
        except SessionExpired:
            if not self.session:
                raise
            # A song-level 403 can mean missing download rights, not an expired
            # account. Check once without retrying/falling back the media URL.
            permission_failure = True
            raw = dict(code=403)
        if self.session and (permission_failure or raw.get('code') in (301, 403)):
            yield from self.verify_session()
            result = media_info(dict(code=403), song_id, download)
            result['reason'] = '账号仍有效，但没有此曲目的下载权限。' if download else '账号仍有效，但没有此曲目的播放权限。'
            return result
        preliminary = media_info(raw, song_id, download)
        if preliminary['unavailable']:
            return preliminary
        duration = 0
        try:
            metadata = yield self.request('/song/detail', dict(ids=song_id))
            songs = metadata.get('songs')
            if isinstance(songs, list):
                for item in songs:
                    if isinstance(item, dict) and str(item.get('id')) == song_id:
                        duration = song_info(item)['duration']
                        break
        except SessionExpired:
            raise
        except (ApiError, ValueError):
            pass
        return media_info(raw, song_id, download, duration)

    def song(self, item_id):
        item_id = music_id(item_id)
        raw = yield self.request('/song/detail', dict(ids=item_id))
        items = raw.get('songs')
        if not isinstance(items, list):
            raise ApiError('接口未返回歌曲列表。')
        song = next((song_info(item) for item in items if isinstance(item, dict) and str(item.get('id')) == item_id), None)
        if song is None:
            raise ApiError('歌曲不可访问或已下架。')
        try:
            lyric = yield self.request('/lyric', dict(id=item_id))
            song['lrc'], song['lrc_status'] = lrc_info(lyric)
        except SessionExpired:
            raise
        except (ApiError, ValueError):
            song.update(lrc='', lrc_status='歌词获取失败；歌曲信息仍可查看，请重试。')
        return song

    def _details(self, ids):
        found, missing_pages = {}, []
        for offset in range(0, len(ids), 200):
            batch = ids[offset:offset + 200]
            self.progress(f'正在读取曲目信息：{min(offset + len(batch), len(ids))}/{len(ids)}')
            try:
                raw = yield self.request('/song/detail', dict(ids=','.join(batch)))
                songs = raw.get('songs')
                if not isinstance(songs, list):
                    raise ApiError('曲目分页格式不兼容。')
                for item in songs:
                    try:
                        song = song_info(item)
                        if song['id'] in batch:
                            found[song['id']] = song
                    except (ValueError, TypeError):
                        continue
            except SessionExpired:
                raise
            except ApiError:
                missing_pages.append(offset // 200 + 1)
        return found, missing_pages

    def playlist(self, item_id):
        item_id = music_id(item_id)
        raw = yield self.request('/playlist/detail', dict(id=item_id))
        playlist = raw.get('playlist', raw.get('result'))
        if not isinstance(playlist, dict):
            raise ApiError('歌单不可访问，或详情接口已变化。')
        title = playlist.get('name')
        if not isinstance(title, str) or len(title) > 1000:
            raise ApiError('歌单标题格式不兼容。')
        total = playlist.get('trackCount')
        if type(total) is not int or total < 0:
            raise ApiError('歌单曲目总数字段不兼容。')
        if total > 20000:
            raise ApiError('歌单超过20000首，暂不导入；没有保存不完整快照。')
        ids = []
        seen = set()
        for item in playlist.get('trackIds', []) if isinstance(playlist.get('trackIds', []), list) else []:
            try:
                song_id = music_id(item.get('id'))
                if song_id not in seen:
                    ids.append(song_id)
                    seen.add(song_id)
            except (ValueError, AttributeError):
                continue
        existing = {}
        for item in playlist.get('tracks', []) if isinstance(playlist.get('tracks', []), list) else []:
            try:
                song = song_info(item)
                existing[song['id']] = song
                if not ids and song['id'] not in seen:
                    seen.add(song['id'])
            except (ValueError, TypeError):
                continue
        if not ids:
            ids = list(existing)
        warnings = []
        # Community /track/all slices the full ordered trackIds on its server.
        # Use it if detail does not expose the entire ID list to this account.
        if len(ids) < total and self.base:
            paged, ordered = {}, []
            paged_seen = set()
            for offset in range(0, total, 200):
                self.progress(f'正在读取歌单分页：{offset}/{total}')
                try:
                    page = yield self.request('/playlist/track/all', dict(id=item_id, limit=200, offset=offset))
                    songs = page.get('songs')
                    if not isinstance(songs, list):
                        raise ApiError('分页格式不兼容。')
                    added = 0
                    for item in songs:
                        try:
                            song = song_info(item)
                            if song['id'] not in paged_seen:
                                paged_seen.add(song['id'])
                                ordered.append(song['id'])
                                added += 1
                            paged[song['id']] = song
                        except (ValueError, TypeError):
                            continue
                    if not added and offset + 200 < total:
                        warnings.append('接口返回重复／空分页，已停止；请刷新重试。')
                        break
                except SessionExpired:
                    raise
                except ApiError:
                    warnings.append(f'第{offset // 200 + 1}页读取失败。')
            if ordered:
                ids, existing = ordered, paged
        needed = [song_id for song_id in ids if song_id not in existing]
        details, failed = yield from self._details(needed)
        existing.update(details)
        if failed:
            warnings.append(f'{len(failed)}批曲目信息失败；可刷新重试。')
        missing = [song_id for song_id in ids if song_id not in existing]
        tracks = [existing.get(song_id, dict(id=song_id, title=f'不可读取的歌曲 {song_id}', artists='', duration=0, unavailable=True)) for song_id in ids]
        count = sum(not item['unavailable'] for item in tracks)
        complete = len(ids) == total and count == total and not warnings
        if not complete:
            warnings.append(f'仅读取{count}/{total}首；缺失、私密或接口限制的内容未冒充完整歌单。')
        return dict(id=item_id, title=title, tracks=tracks, total=total, count=count, complete=complete,
                    warnings=warnings, missing=missing, order='云端歌单顺序；未读取的分页未重新排序')

    def collections(self):
        if not self.session:
            raise SessionExpired('请先扫码登录独立账号会话。')
        uid = self.session['uid']
        entries, seen, warnings = [], set(), []
        for offset in range(0, 10000, 100):
            self.progress(f'正在读取账号歌单分页：已读取{len(entries)}个')
            try:
                raw = yield self.request('/user/playlist', dict(uid=uid, limit=100, offset=offset))
                page = raw.get('playlist')
                if not isinstance(page, list):
                    raise ApiError('账号歌单格式不兼容。')
                added = 0
                invalid = 0
                for item in page:
                    try:
                        item_id = music_id(item.get('id'))
                        if item_id in seen:
                            continue
                        title = item.get('name')
                        if not isinstance(title, str) or len(title) > 1000:
                            invalid += 1
                            continue
                        creator = item.get('creator') or {}
                        music_id(creator.get('userId'))
                        owned = str(creator.get('userId')) == uid
                        entries.append(dict(id=item_id, title=title, owned=owned,
                                            liked=item.get('specialType') == 5 and owned))
                        seen.add(item_id)
                        added += 1
                    except (ValueError, TypeError, AttributeError):
                        invalid += 1
                        continue
                if invalid:
                    warnings.append(f'账号歌单第{offset // 100 + 1}页有{invalid}条格式不兼容，未冒充完整列表。')
                more = raw.get('more')
                if more is False or (more is None and len(page) < 100):
                    break
                if not added:
                    warnings.append('账号歌单分页重复／为空，读取未完成。')
                    break
            except SessionExpired:
                raise
            except ApiError:
                warnings.append(f'账号歌单第{offset // 100 + 1}页失败；请刷新。')
                break
        else:
            warnings.append('账号歌单超过10000个，已停止读取。')
        return dict(created=[item for item in entries if item['owned']],
                    collected=[item for item in entries if not item['owned']],
                    liked_playlist=next((item['id'] for item in entries if item['liked']), None),
                    complete=not warnings, warnings=warnings)

    def likes(self):
        if not self.session:
            raise SessionExpired('请先登录。')
        collections = yield from self.collections()
        if collections['liked_playlist']:
            return (yield from self.playlist(collections['liked_playlist']))
        raw = yield self.request('/likelist', dict(uid=self.session['uid']))
        values = raw.get('ids')
        if not isinstance(values, list) or len(values) > 20000:
            raise ApiError('喜欢列表字段不兼容或超过20000首。')
        ids = list(dict.fromkeys(music_id(value) for value in values))
        details, failed = yield from self._details(ids)
        tracks = [details[item] for item in ids if item in details]
        return dict(id=self.session['uid'], title='我喜欢的音乐', download_source='likes', tracks=tracks, total=len(ids),
                    count=len(tracks), complete=len(tracks) == len(ids) and not failed,
                    warnings=['未找到可核对顺序的喜欢歌单；按接口ID返回顺序展示，不代表客户端排序。']
                             + (['部分曲目信息读取失败，请刷新。'] if len(tracks) != len(ids) else []),
                    order='无序喜欢ID接口的返回顺序')

    def qr(self):
        raw = yield self.request('/login/qr/key', authenticated=False)
        data = raw.get('data', raw)
        key = data.get('unikey') if isinstance(data, dict) else None
        if not isinstance(key, str) or not key or len(key) > 512:
            raise ApiError('扫码key字段不兼容。')
        if not self.base:
            from .direct import qr_url
            return dict(key=key, url=qr_url(key))
        raw = yield self.request('/login/qr/create', dict(key=key, qrimg='true'), authenticated=False)
        data = raw.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('qrimg'), str):
            raise ApiError('接口没有返回二维码图像，请核对API版本。')
        return dict(key=key, image=data['qrimg'])

    def check_qr(self, key):
        if not self.base:
            from .direct import qr_url
            qr_url(key)
        raw = yield self.request('/login/qr/check', dict(key=key), authenticated=False, allowed=(800, 801, 802, 803))
        code = raw.get('code')
        if code != 803:
            return dict(code=code)
        cookie = raw.get('cookie') if self.base else raw.get('_direct_cookie')
        if not isinstance(cookie, str) or not cookie:
            raise ApiError('扫码已确认，但未收到独立登录凭据，请重新扫码。')
        status = yield self.request('/login/status', cookie=cookie)
        data = status.get('data', status)
        profile = data.get('profile') if isinstance(data, dict) else None
        if not isinstance(profile, dict) or not profile.get('userId'):
            raise SessionExpired('扫码已确认，但账号会话未就绪，请重新扫码。')
        return dict(code=803, session=session_data(dict(api=self.base, uid=profile['userId'],
                    nickname=profile.get('nickname', ''), cookie=status.get('_direct_cookie', cookie)), self.base))

    def verify_session(self):
        if not self.session:
            raise SessionExpired('尚未登录。')
        raw = yield self.request('/login/status')
        data = raw.get('data', raw)
        profile = data.get('profile') if isinstance(data, dict) else None
        if not isinstance(profile, dict) or str(profile.get('userId')) != self.session['uid']:
            raise SessionExpired('会话已过期，请重新扫码。')
        return dict(uid=self.session['uid'], nickname=profile.get('nickname', ''))
