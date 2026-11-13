"""Read Bilibili lists; retain only normal video URLs for the existing player."""
from dataclasses import dataclass
import hashlib
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .bilibili_links import video_url


HOSTS = {'bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'space.bilibili.com', 'b23.tv'}
MAX_ITEMS = 5000
MAX_PAGES = 200
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36'


@dataclass(frozen=True)
class Source:
    kind: str
    id: str = ''
    mid: str = ''
    url: str = ''


def number(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise ValueError('链接里的编号不正确，请重新复制完整链接。')
    return value


def checked_url(url, api=False):
    try:
        p = urlsplit(url)
        if (p.scheme not in ('http', 'https') or p.hostname not in ({'api.bilibili.com'} if api else HOSTS)
                or p.username or p.password or p.port not in (None, 80, 443)
                or '\\' in url or any(ord(c) < 32 for c in url)):
            raise ValueError()
        return p
    except (ValueError, TypeError):
        raise ValueError('请使用 B站官方视频、合集、空间或收藏夹链接。') from None


def parse_source(value):
    """Accept browser links and the URL inside a copied app share message."""
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('请粘贴 B站链接。')
    value = value.strip()
    if re.fullmatch(r'BV[0-9A-Za-z]{10}|av[1-9][0-9]*', value):
        value = 'https://www.bilibili.com/video/' + value
    if re.fullmatch(r'[1-9][0-9]{0,18}', value):
        value = 'https://space.bilibili.com/' + value
    matches = re.findall(r'https?://[^\s<>"「」【】]+', value)
    if len(matches) != 1:
        raise ValueError('请一次粘贴一个 B站链接，也可以填写 UP 主 UID。')
    url = matches[0].rstrip('，。；！）》),.;!')
    p = checked_url(url)
    q = parse_qs(p.query)
    def param(key, default=''):
        values = q.get(key, [default])
        if len(values) != 1:
            raise ValueError('链接包含重复参数，请重新复制。')
        return values[0]
    if p.hostname == 'b23.tv':
        if not re.fullmatch(r'/[A-Za-z0-9]+/?', p.path):
            raise ValueError('B站短链接格式不正确。')
        return Source('short', url=url)
    if p.path.startswith('/video/'):
        return Source('video', url=video_url(url))
    if p.hostname == 'space.bilibili.com':
        m = re.fullmatch(r'/([1-9][0-9]*)(.*)', p.path.rstrip('/'))
        if m:
            mid, suffix = number(m[1]), m[2]
            lists = re.fullmatch(r'/lists/([1-9][0-9]*)', suffix)
            if lists:
                kind = param('type', 'season')
                if kind not in ('season', 'series'):
                    raise ValueError('暂不支持这种 B站列表。')
                return Source(kind, number(lists[1]), mid, url)
            if suffix in ('/channel/collectiondetail', '/channel/seriesdetail'):
                return Source('season' if 'collection' in suffix else 'series', number(param('sid')), mid, url)
            if suffix == '/favlist' and param('fid'):
                return Source('season' if param('ftype') == 'collect' else 'favorite', number(param('fid')), mid, url)
            if suffix in ('', '/lists', '/channel', '/favlist'):
                return Source('space', mid=mid, url=url)
            if suffix in ('/video', '/upload/video'):
                return Source('uploads', mid=mid, url=url)
    m = re.fullmatch(r'/(?:list|medialist/(?:play|detail))/ml([1-9][0-9]*)/?', p.path)
    if m:
        return Source('favorite', number(m[1]), url=url)
    m = re.fullmatch(r'/(?:list|medialist/play)/([1-9][0-9]*)/?', p.path)
    if m:
        mid = number(m[1])
        if param('business') in ('space_collection', 'space_series'):
            return Source('season' if param('business') == 'space_collection' else 'series',
                          number(param('business_id')), mid, url)
        if param('sid'):
            return Source('series', number(param('sid')), mid, url)
        if param('season_id'):
            return Source('season', number(param('season_id')), mid, url)
        if param('fid'):
            return Source('favorite', number(param('fid')), mid, url)
    raise ValueError('未识别这个链接。请复制视频、UP 主空间、合集或收藏夹的链接。')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ImportCancelled(Exception):
    pass


class BilibiliImport:
    """A single cancellable transaction: errors never replace the saved queue."""
    def __init__(self, cookie='', stopped=None, progress=None):
        self.cookie = cookie if isinstance(cookie, str) and not any(c in cookie for c in '\r\n\0') else ''
        self.stopped = stopped or threading.Event()
        self.progress = progress or (lambda _: None)
        self.deadline = time.monotonic() + 180
        self.opener = build_opener(NoRedirect())

    def check(self):
        if self.stopped.is_set():
            raise ImportCancelled()
        if time.monotonic() > self.deadline:
            raise ValueError('读取超时，原有歌单没有变化。请稍后重试或选择较小的列表。')

    def raw(self, url, api=True):
        self.check()
        checked_url(url, api=api)
        headers = {'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/', 'Accept': 'application/json'}
        if api and self.cookie:
            headers['Cookie'] = self.cookie
        try:
            with self.opener.open(Request(url, headers=headers), timeout=12) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('B站返回的列表过大，请改用较小的合集。')
            self.check()
            return data
        except HTTPError as error:
            if not api and error.code in (301, 302, 303, 307, 308):
                return urljoin(url, error.headers.get('Location', ''))
            if error.code in (403, 412, 429):
                raise ValueError('B站暂时限制了读取，请在登录窗口完成验证后稍后重试。') from None
            raise ValueError(f'读取 B站失败（HTTP {error.code}），请稍后重试。') from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('连接 B站失败，请检查网络后重试。') from None

    def api(self, path, **params):
        try:
            result = json.loads(self.raw('https://api.bilibili.com' + path + '?' + urlencode(params)))
        except (ValueError, UnicodeError) as error:
            if isinstance(error, json.JSONDecodeError) or isinstance(error, UnicodeError):
                raise ValueError('B站返回了验证页面，请在登录窗口完成验证后重试。') from None
            raise
        if not isinstance(result, dict):
            raise ValueError('B站返回的数据格式不正确。')
        code = result.get('code')
        anonymous_nav = path == '/x/web-interface/nav' and code == -101 and isinstance(result.get('data'), dict)
        if code in (-101, -403) and not anonymous_nav:
            raise ValueError('这个收藏夹需要登录本人账号，或未向你开放。请先点击“登录 B站”。')
        if code in (-352, -412, -509, -799, -401):
            raise ValueError('B站暂时限制了读取，请登录或完成网页验证后稍后重试。')
        if code != 0 and not anonymous_nav:
            raise ValueError(f'B站未能返回列表（状态 {code}），链接可能已失效或需要登录。')
        data = result.get('data')
        if not isinstance(data, dict):
            raise ValueError('B站没有返回可读取的列表。')
        return data

    def resolve(self, value):
        source = value if isinstance(value, Source) else parse_source(value)
        for _ in range(5):
            if source.kind != 'short':
                return source
            url = self.raw(source.url, api=False)
            if not isinstance(url, str):
                raise ValueError('短链接没有跳转，请在浏览器中展开后复制地址。')
            source = parse_source(url)
        raise ValueError('短链接跳转次数过多，请复制浏览器里的完整地址。')

    def account(self):
        data = self.api('/x/web-interface/nav')
        if not data.get('isLogin'):
            raise ValueError('请先点击“登录 B站”，完成登录后再读取我的收藏夹。')
        return number(data.get('mid')), str(data.get('uname', ''))[:100]

    def read(self, value):
        source = self.resolve(value)
        if source.kind in ('space', 'mine'):
            mid, nickname = self.account() if source.kind == 'mine' else (source.mid, '')
            result = self.catalogue(mid, only_favorites=source.kind == 'mine')
            if source.kind == 'mine':
                result['account'] = nickname
            return result
        return self.tracks(source)

    def catalogue(self, mid, only_favorites=False):
        choices, seen, warnings = [], set(), []
        def append(kind, identifier, title, count, owner=mid):
            key = kind, str(identifier)
            if key in seen:
                return
            seen.add(key)
            choices.append(dict(title=str(title)[:200], count=count,
                                source=Source(kind, number(identifier), number(owner))))
        # Independent lists may have different visibility permissions.
        if not only_favorites:
            choices.append(dict(title='全部视频投稿', count=None, source=Source('uploads', mid=mid)))
            try:
                for page in range(1, MAX_PAGES + 1):
                    data = self.api('/x/polymer/web-space/seasons_series_list', mid=mid, page_num=page, page_size=20)
                    items = data.get('items_lists') or {}
                    groups = [('season', items.get('seasons_list') or []), ('series', items.get('series_list') or [])]
                    size = 0
                    for kind, rows in groups:
                        size += len(rows)
                        for item in rows:
                            meta = item.get('meta') or {}
                            append(kind, meta.get('season_id' if kind == 'season' else 'series_id'),
                                   meta.get('name', '未命名列表'), meta.get('total', 0))
                    total = (items.get('page') or data.get('page') or {}).get('total')
                    if not size or (isinstance(total, int) and page * 20 >= total):
                        break
                    if page == MAX_PAGES:
                        raise ValueError('合集太多，请复制具体合集的链接。')
            except ValueError as error:
                warnings.append(str(error))
        try:
            data = self.api('/x/v3/fav/folder/created/list-all', up_mid=mid)
            for folder in data.get('list') or []:
                append('favorite', folder.get('id'), folder.get('title', '收藏夹'), folder.get('media_count', 0))
        except ValueError as error:
            warnings.append(str(error))
        # Include followed favorites as well as one's own folders.
        if only_favorites:
            try:
                for page in range(1, MAX_PAGES + 1):
                    data = self.api('/x/v3/fav/folder/collected/list', up_mid=mid, pn=page, ps=20, platform='web')
                    for folder in data.get('list') or []:
                        is_season = folder.get('type') in (21, '21', 'collection', 'collect', 'season')
                        owner = (folder.get('upper') or {}).get('mid') or folder.get('mid') or mid
                        append('season' if is_season else 'favorite', folder.get('id'),
                               folder.get('title', '收藏夹'), folder.get('media_count', 0), owner)
                    more = data.get('has_more', page * 20 < int(data.get('count', 0)))
                    if not more:
                        break
                    if not data.get('list'):
                        raise ValueError('B站漏回了收藏夹列表，请稍后重新读取。')
                    if page == MAX_PAGES:
                        raise ValueError('收藏夹太多，请复制具体收藏夹的链接。')
            except ValueError as error:
                warnings.append(str(error))
        self.check()
        return dict(choices=choices, warning='；'.join(dict.fromkeys(warnings)))

    def signed_uploads(self, mid, page):
        nav = self.api('/x/web-interface/nav') if not hasattr(self, '_wbi_key') else None
        if nav is not None:
            images = nav.get('wbi_img') or {}
            key = ''.join(urlsplit(images.get(k, '')).path.rsplit('/', 1)[-1].split('.')[0] for k in ('img_url', 'sub_url'))
            order = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13)
            if len(key) < 64:
                raise ValueError('B站投稿列表验证暂时不可用，请改用具体合集链接。')
            self._wbi_key = ''.join(key[i] for i in order)
        params = dict(mid=mid, pn=page, ps=30, order='pubdate', tid=0, keyword='', platform='web', wts=int(time.time()))
        query = urlencode(sorted((k, re.sub(r"[!'()*]", '', str(v))) for k, v in params.items()))
        return self.api('/x/space/wbi/arc/search', **params, w_rid=hashlib.md5((query + self._wbi_key).encode()).hexdigest())

    def tracks(self, source):
        tracks, seen, skipped = [], set(), 0
        title = {'favorite': '收藏夹', 'season': '合集', 'series': '视频列表', 'uploads': 'UP 主投稿'}.get(source.kind, '视频')
        def append(item, part=1, part_title=''):
            nonlocal skipped
            if not isinstance(item, dict):
                skipped += 1
                return
            if item.get('type', 2) != 2 or item.get('title') in ('已失效视频', '已删除视频', '视频已失效'):
                skipped += 1
                return
            identifier = item.get('bvid') or item.get('bv_id') or (f"av{item['aid']}" if item.get('aid') else '')
            try:
                url = video_url(f'https://www.bilibili.com/video/{identifier}/?p={part}')
            except ValueError:
                skipped += 1
                return
            if url not in seen:
                seen.add(url)
                tracks.append(dict(url=url, title=str(part_title or item.get('title') or identifier)[:200]))
                if len(tracks) > MAX_ITEMS:
                    raise ValueError(f'列表超过 {MAX_ITEMS} 首，请选择较小的合集；本次没有写入。')
        if source.kind == 'video':
            identifier = urlsplit(source.url).path.strip('/').split('/')[-1]
            params = {'bvid': identifier} if identifier.startswith('BV') else {'aid': identifier[2:]}
            data = self.api('/x/web-interface/view', **params)
            season = data.get('ugc_season') or {}
            if season.get('id'):
                return self.tracks(Source('season', number(season['id']), number(season.get('mid') or data['owner']['mid'])))
            pages = data.get('pages') or []
            if pages:
                for item in pages:
                    append(data, item.get('page', 1), (str(data.get('title', '视频')) + ' · ' + str(item.get('part', ''))) if len(pages) > 1 else '')
            else:
                append(data)
            title = str(data.get('title', '视频'))[:200]
        else:
            fingerprints = set()
            for page in range(1, MAX_PAGES + 1):
                self.check()
                if source.kind == 'favorite':
                    data = self.api('/x/v3/fav/resource/list', media_id=source.id, pn=page, ps=20, platform='web')
                    items = data.get('medias') or []
                    title = str((data.get('info') or {}).get('title') or title)[:200]
                    more = bool(data.get('has_more'))
                elif source.kind in ('season', 'series'):
                    if source.kind == 'season':
                        data = self.api('/x/polymer/web-space/seasons_archives_list', mid=source.mid,
                                        season_id=source.id, page_num=page, page_size=30, sort_reverse='false')
                    else:
                        data = self.api('/x/series/archives', mid=source.mid, series_id=source.id, pn=page, ps=30, sort='asc')
                    items = data.get('archives') or []
                    title = str((data.get('meta') or {}).get('name') or title)[:200]
                    total = (data.get('page') or {}).get('total')
                    more = page * 30 < total if isinstance(total, int) else len(items) >= 30
                elif source.kind == 'uploads':
                    data = self.signed_uploads(source.mid, page)
                    items = (data.get('list') or {}).get('vlist') or []
                    more = page * 30 < int((data.get('page') or {}).get('count', 0))
                else:
                    raise ValueError('无法读取这个列表。')
                fingerprint = json.dumps(items, sort_keys=True, ensure_ascii=True)
                if (more and not items) or (items and fingerprint in fingerprints):
                    raise ValueError('B站重复或漏回了某页列表，本次没有写入，请稍后重试。')
                fingerprints.add(fingerprint)
                for item in items:
                    append(item)
                self.progress(f'正在读取{title}：第 {page} 页，已找到 {len(tracks)} 首…')
                if not more:
                    break
                if page == MAX_PAGES:
                    raise ValueError('列表页数太多，请选较小的合集；本次没有写入。')
                if self.stopped.wait(.2):
                    raise ImportCancelled()
        self.check()
        return dict(tracks=tracks, title=title, skipped=skipped)
