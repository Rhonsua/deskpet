"""Direct Kugou protocol. Adapted from MakcRe/KuGouMusicApi (MIT); see LICENSE."""
import base64, hashlib, json, re, time
from dataclasses import dataclass, field
from urllib.parse import quote

class ApiError(ValueError): pass
class SessionExpired(ApiError): pass
@dataclass
class Request:
    url: str
    params: dict = field(repr=False)
    headers: dict = field(default_factory=dict, repr=False)
    body: str = field(default='', repr=False)
    redirect_probe: bool = False

def song_id(value):
    value = str(value or '').upper()
    if not re.fullmatch(r'[A-F0-9]{32}', value): raise ApiError('歌曲标识无效。')
    return value

def normalize(row):
    h = song_id(row.get('hash') or row.get('FileHash') or row.get('audio_info', {}).get('hash'))
    title = row.get('songname') or row.get('SongName') or row.get('filename') or row.get('FileName') or row.get('name') or h
    artists = row.get('singername') or row.get('SingerName') or row.get('singerinfo') or ''
    if isinstance(artists, list): artists = ' / '.join(str(x.get('name','')) if isinstance(x,dict) else str(x) for x in artists)
    duration = row.get('duration') or row.get('Duration') or 0
    return dict(id=h,hash=h,title=title,artists=artists,duration=int(row.get('timelen') or int(duration)*1000),album_id=row.get('album_id') or row.get('AlbumID') or 0,album_audio_id=row.get('album_audio_id') or row.get('MixSongID') or row.get('mixsongid') or 0,pay_type=row.get('PayType',row.get('pay_type')))

class Service:
    def __init__(self, session=None, progress=None, cache=None):
        self.session = session or {}; self.progress = progress; self.cache = cache
    def request(self, path, params, router='', web=False, body=None, host='https://gateway.kugou.com'):
        p = dict(dfid='-',mid='0',uuid='-',appid=1005,clientver=20489,clienttime=int(time.time()))
        p.update(params)
        bodytext = json.dumps(body, ensure_ascii=False, separators=(',',':')) if body is not None else ''
        salt = 'NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt' if web else 'OIlwieks28dk2k092lksi2UIkp'
        p['signature'] = hashlib.md5((salt+''.join(f'{k}={p[k]}' for k in sorted(p))+bodytext+salt).encode()).hexdigest()
        return Request(host+path,p,{'x-router':router} if router else {},bodytext)
    def search(self, query):
        if not str(query).strip(): raise ApiError('请输入搜索词。')
        raw = yield self.request('/v2/search/song',dict(keyword=str(query)[:200],page=1,pagesize=30,platform='AndroidFilter',iscorrection=1,privilegefilter=0,area_code=1,dopicfull=1), 'complexsearch.kugou.com')
        data=raw.get('data') or {}; rows=data.get('lists') or data.get('info') or []; tracks=[]
        for row in rows:
            try: tracks.append(normalize(row))
            except (ValueError,TypeError): pass
        total=int(data.get('total') or len(rows)); return dict(tracks=tracks,total=total,complete=len(tracks)>=total)
    def resolve_playlist(self, value):
        from .links import extract_url, playlist_id, safe_share_url
        try: item_id=playlist_id(value)
        except ValueError:
            url=extract_url(value)
            for _ in range(5):
                url=safe_share_url(url)
                raw=yield Request(url,{},redirect_probe=True)
                target=raw.get('location')
                if not target: raise ApiError('分享链接未返回可识别的酷狗歌单地址。')
                from urllib.parse import urljoin
                url=safe_share_url(urljoin(url,target))
                try:
                    item_id=playlist_id(url)
                    break
                except ValueError: pass
            else: raise ApiError('酷狗分享链接重定向次数过多。')
        return (yield from self.playlist(item_id))

    def playlist(self, item_id):
        item_id=str(item_id)
        private=re.fullmatch(r'user_(\d{1,20})_([01])',item_id)
        if not private and not re.fullmatch(r'collection_[A-Za-z0-9_-]{1,110}',item_id):
            raise ApiError('请使用完整的酷狗歌单标识；旧版数字链接暂不支持。')
        if private and not self.session.get('token'): raise SessionExpired('请先扫码登录。')
        tracks=[]; total=None; missing=[]; warnings=[]; data={}; title=item_id; seen=set()
        for page in range(1,101):
            try:
                if private:
                    uid=str(self.session['userid']); token=self.session['token']
                    request=self.request('/v4/get_list_all_file_v3',{},'cloudlist.service.kugou.com',body=dict(listid=int(private.group(1)),userid=uid,type=int(private.group(2)),page=page,pagesize=30,area_code=1,allplatform=1,show_cover=1,token=token))
                else:
                    request=self.request('/pubsongs/v2/get_other_list_file_nofilt',dict(area_code=1,begin_idx=(page-1)*30,plat=1,type=1,mode=1,personal_switch=1,pagesize=30,global_collection_id=item_id))
                raw=yield request
                data=raw.get('data')
                if not isinstance(data,dict): raise ApiError('酷狗未返回歌单数据。')
                count=data.get('total',data.get('count'))
                if type(count) is not int or count < 0: raise ApiError('酷狗未返回有效歌单总数。')
                if total is not None and count != total: raise ApiError('歌单读取期间总数发生变化。')
                total=count
                rows=next((data[k] for k in ('songs','list','info','files') if isinstance(data.get(k),list)),None)
                if rows is None: raise ApiError('酷狗未返回歌曲列表。')
                title=str((data.get('list_info') or {}).get('name') or data.get('name') or title)
                for row in rows:
                    try:
                        track = normalize(row)
                        if track['id'] in seen:
                            if page not in missing: missing.append(page)
                            warnings.append(f'第{page}页包含重复曲目，已去重。')
                            continue
                        seen.add(track['id'])
                        tracks.append(track)
                    except (ValueError,TypeError,AttributeError,KeyError):
                        if page not in missing: missing.append(page)
                        warnings.append(f'第{page}页有歌曲缺少有效标识或数据格式不兼容。')
                if not rows:
                    if len(tracks)<total: missing.append(page); warnings.append(f'第{page}页提前结束。')
                    break
                if page*30>=total: break
            except ApiError as error:
                if not tracks: raise
                if page not in missing: missing.append(page)
                warnings.append(f'第{page}页读取失败：{error}')
                break
        else:
            missing.append(101); warnings.append('已达到100页上限。')
        complete=total is not None and len(tracks)==total and not missing
        return dict(id=item_id,title=title,tracks=tracks,total=total if total is not None else 0,complete=complete,missing_pages=missing,warnings=list(dict.fromkeys(warnings)))
    def qr_create(self):
        raw=yield self.request('/v2/qrcode',dict(appid=1001,type=1,plat=4,qrcode_txt='https://h5.kugou.com/apps/loginQRCode/html/index.html?appid=1005&',srcappid=2919),web=True,host='https://login-user.kugou.com')
        key=str((raw.get('data') or {}).get('qrcode') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',key): raise ApiError('酷狗未返回有效二维码。')
        return dict(key=key,url='https://h5.kugou.com/apps/loginQRCode/html/index.html?qrcode='+quote(key))
    def qr_check(self,key):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,512}',str(key)): raise ApiError('二维码无效。')
        raw=yield self.request('/v2/get_userinfo_qrcode',dict(plat=4,appid=1005,srcappid=2919,qrcode=key,dev=''),web=True,host='https://login-user.kugou.com')
        data=raw.get('data') or {}; state={0:'expired',1:'waiting',2:'scanned',4:'confirmed'}.get(data.get('status'),'rejected'); result={'status':state}
        if state=='confirmed':
            if not data.get('userid') or not data.get('token'): raise ApiError('登录响应缺少凭据。')
            result['session']={'userid':str(data['userid']),'token':str(data['token']),'nickname':str(data.get('nickname') or '')}
        return result
    def collections(self):
        if not self.session.get('token'): raise SessionExpired('请先扫码登录。')
        uid=self.session['userid']; token=self.session['token']; rows=[]; total=None; warnings=[]; seen=set()
        pagesize=30
        for page in range(1,101):
            try:
                raw=yield self.request('/v7/get_all_list',dict(plat=1,userid=uid,token=token), 'cloudlist.service.kugou.com',body=dict(userid=uid,token=token,total_ver=979,type=2,page=page,pagesize=pagesize))
                data=raw.get('data')
                if not isinstance(data,dict): raise ApiError('酷狗未返回个人歌单数据。')
                batch=next((data[k] for k in ('info','list','lists') if isinstance(data.get(k),list)),None)
                if batch is None: raise ApiError('酷狗未返回个人歌单列表。')
                # The ordinary app returns info + category counters, not total.
                # Do not sum list_count/collect_count/album_count: their scopes
                # are not documented. Page using the raw (unfiltered) rows.
                count=data.get('total',data.get('count'))
                if count is not None:
                    if type(count) is not int or count < 0: raise ApiError('酷狗未返回有效个人歌单总数。')
                    if total is not None and count!=total: raise ApiError('个人歌单读取期间总数发生变化。')
                    total=count
                elif total is not None or not isinstance(data.get('info'),list):
                    raise ApiError('酷狗未返回有效个人歌单总数。')
            except SessionExpired:
                raise
            except ApiError as error:
                if not rows: raise
                warnings.append(f'第{page}页读取失败：{error}')
                break
            before=len(rows)
            for x in batch:
                if not isinstance(x,dict): warnings.append('歌单条目格式不兼容。'); continue
                ident=str(x.get('listid',x.get('list_id',''))); typ=x.get('type',0)
                if not re.fullmatch(r'\d{1,20}',ident) or str(typ) not in ('0','1'):
                    warnings.append('歌单条目缺少有效标识或类型。'); continue
                item_id=f'user_{ident}_{typ}'
                if item_id in seen:
                    warnings.append('个人歌单包含重复分页，已去重。')
                    continue
                seen.add(item_id)
                rows.append(dict(id=item_id,title=x.get('name') or x.get('list_name') or ident,count=x.get('count') or x.get('file_count') or 0))
            if batch and len(rows)==before:
                warnings.append('本页没有新的有效歌单，已停止重复读取。')
                break
            if not batch:
                if total is not None and len(rows)<total: warnings.append('个人歌单列表提前结束。')
                break
            if total is not None:
                if page*pagesize>=total: break
            elif len(batch)<pagesize: break
        else: warnings.append('已达到100页上限。')
        return dict(playlists=rows,complete=(total is None or len(rows)==total) and not warnings,warnings=list(dict.fromkeys(warnings)))
    def song(self,track_or_id):
        track=track_or_id.copy() if isinstance(track_or_id,dict) else dict(id=song_id(track_or_id),hash=song_id(track_or_id),title=str(track_or_id),artists='',duration=0)
        h=song_id(track.get('hash') or track.get('id'))
        try:
            raw=yield self.request('/search',dict(ver=1,man='yes',client='pc',hash=h),host='https://lyrics.kugou.com')
            candidates=raw.get('candidates') or []
            if not candidates: return dict(track,lrc='',lrc_status='没有找到歌词')
            candidate=candidates[0]; raw=yield self.request('/download',dict(ver=1,client='pc',id=candidate['id'],accesskey=candidate['accesskey'],fmt='lrc',charset='utf8'),host='https://lyrics.kugou.com')
            lrc=base64.b64decode(raw.get('content',''),validate=True).decode('utf-8-sig'); return dict(track,lrc=lrc,lrc_status='已获取歌词')
        except (ApiError,ValueError,KeyError,UnicodeError): return dict(track,lrc='',lrc_status='歌词获取失败')
    def media(self,track_or_id,download=False):
        try:
            result=yield from self._media(track_or_id,download)
        except SessionExpired:
            raise
        except ApiError as error:
            if not download: raise
            h=song_id(track_or_id.get('hash') or track_or_id.get('id') if isinstance(track_or_id,dict) else track_or_id)
            result=dict(id=h,url='',unavailable=True,trial=False,reason=str(error))
        if download and result['unavailable']:
            # Standard Kugou may return a complete, ordinary MP3 for playback
            # while its separate download endpoint returns no URL. Save that
            # stream only when this same account can obtain the full audio.
            try:
                playable=yield from self._media(track_or_id,False)
            except SessionExpired:
                raise
            except ApiError:
                return result
            if (not playable['unavailable'] and not playable['trial']
                    and playable['extension']=='mp3' and playable['size']>0
                    and playable['duration_ms']>0):
                return playable
        return result

    def _media(self,track_or_id,download=False):
        h=song_id(track_or_id.get('hash') or track_or_id.get('id') if isinstance(track_or_id,dict) else track_or_id)
        track=track_or_id if isinstance(track_or_id,dict) else {}
        uid=str(self.session.get('userid') or '0'); token=str(self.session.get('token') or '')
        key=hashlib.md5((h.lower()+'57ae12eb6890223e355ccfcb74edf70d'+'1005'+'0'+uid).encode()).hexdigest()
        params=dict(album_id=track.get('album_id') or 0,area_code=1,hash=h.lower(),ssa_flag='is_fromtrack',version=11430,page_id=151369488,quality=128,album_audio_id=track.get('album_audio_id') or 0,behavior='download' if download else 'play',pid=2,cmd=26,pidversion=3001,IsFreePart=0,ppage_id='463467626,350369493,788954147',cdnBackup=1,module='',clientver=11430,key=key)
        if token: params.update(userid=uid,token=token)
        raw=yield self.request('/v5/url',params,'trackercdn.kugou.com')
        from .media import validate_media_url
        urls=[]
        candidates=raw.get('url') or []
        if isinstance(candidates,str): candidates=[candidates]
        for candidate in candidates:
            try:
                candidate=validate_media_url(candidate)
                if candidate not in urls: urls.append(candidate)
            except ValueError: pass
        duration=int(raw.get('timeLength') or 0)*1000; full=int(track.get('duration') or 0)
        trial=bool(raw.get('hash_offset')) or bool(full and duration and duration+2000<full)
        allowed=raw.get('status')==1 and raw.get('priv_status')==1 and bool(urls)
        if download: allowed=allowed and not trial and duration>0 and int(raw.get('fileSize') or 0)>0
        if allowed: reason='仅提供试听' if trial else ''
        elif trial: reason='酷狗仅返回试听片段，未保存为完整 MP3。'
        elif raw.get('status')==1 and raw.get('priv_status')==1 and candidates:
            reason='酷狗返回的音频服务器暂未适配。'
        else: reason='酷狗未返回可用的'+('完整 MP3' if download else '播放地址')+'，请确认当前账号可播放该曲目。'
        return dict(id=h,url=urls[0] if allowed else '',urls=urls if allowed else [],
                    extension=str(raw.get('extName') or 'mp3').lower(),size=int(raw.get('fileSize') or 0),
                    duration_ms=duration,trial=trial,trial_start_ms=0,unavailable=not allowed,reason=reason,
                    source_kind='download' if download else 'playback')
