"""Cancellable single-file CDN transfer. No session cookies or user library writes."""
import os
from pathlib import Path
import re
import tempfile
import time
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply

MAX_BYTES=200*1024*1024
ALLOWED_EXTENSIONS={'mp3','flac','wav','ogg','m4a','aac'}

def validate_media_url(url):
    # Kept patchable for synthetic localhost tests; production policy lives in media.
    from .media import validate_media_url as validate
    return validate(url)

def safe_stem(value):
    if not isinstance(value,str):raise ValueError('文件名须为文字')
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_',value).strip().rstrip('. ')[:100].rstrip('. ')
    if not value:value='网易云音频'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',value):value='_'+value
    return value

def _commit(part,directory,stem,extension,paired_lrc=False,overwrite=False):
    if overwrite:
        target=directory/f'{stem}.{extension}'
        os.replace(part,target)
        return target
    # Both platform paths commit atomically and refuse a racing existing destination.
    for index in range(10000):
        name=f'{stem}{" ("+str(index)+")" if index else ""}.{extension}'
        target=directory/name
        if paired_lrc and target.with_suffix('.lrc').exists():continue
        try:
            if os.name=='nt':os.rename(part,target) # Windows rename atomically refuses an existing target.
            else:os.link(part,target)
        except FileExistsError:continue
        if os.name!='nt':part.unlink()
        return target
    raise OSError('可用文件名过多，请换一个名称')

def export_lrc(directory,stem,lrc,*,overwrite=False):
    if not isinstance(lrc,str) or not lrc.strip():raise ValueError('没有可导出的歌词')
    data=lrc.encode('utf-8')
    if len(data)>1024*1024:raise ValueError('歌词超过1MiB限制')
    directory=Path(directory).resolve()
    if not directory.is_dir():raise ValueError('请选择已存在的保存文件夹')
    fd,name=tempfile.mkstemp(prefix='.tianyi-lrc-',suffix='.part',dir=directory)
    part=Path(name)
    try:
        with os.fdopen(fd,'wb') as output:output.write(data);output.flush();os.fsync(output.fileno())
        return str(_commit(part,directory,safe_stem(stem),'lrc',overwrite=overwrite))
    finally:part.unlink(missing_ok=True)

def audio_extension(prefix):
    if prefix.startswith(b'ID3') or (len(prefix)>1 and prefix[0]==255 and prefix[1]&224==224 and prefix[1]&6!=0):return 'mp3'
    if prefix.startswith(b'fLaC'):return 'flac'
    if prefix.startswith(b'RIFF') and prefix[8:12]==b'WAVE':return 'wav'
    if prefix.startswith(b'OggS'):return 'ogg'
    if len(prefix)>=12 and prefix[4:8]==b'ftyp' and prefix[8:12] in (b'M4A ',b'M4B ',b'isom',b'iso2',b'mp41',b'mp42'):return 'm4a'
    if len(prefix)>1 and prefix[0]==255 and prefix[1]&246==240:return 'aac'
    raise ValueError('返回内容没有可识别的音频头，未保存为音乐文件')

class Downloader(QObject):
    completed=Signal(str,str)
    skipped=Signal()
    failed=Signal(str)
    warning=Signal(str)
    progress=Signal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.manager=QNetworkAccessManager(self);self.reply=None;self.part=None;self.file=None
        self.resolve_conflict=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self._fail('下载超过30秒无响应，已停止'))
        self.received=0;self.total=0;self.expected_size=0;self.prefix=b'';self.directory=None;self.stem='';self.lrc='';self.started=0
    def start(self,url,directory,stem,extension,lrc='',expected_size=0):
        self.cancel()
        try:
            url=validate_media_url(url)
            extension=str(extension).lower().lstrip('.')
            if extension not in ALLOWED_EXTENSIONS:raise ValueError('下载接口未提供支持的音频格式')
            if type(expected_size) is not int or expected_size<0 or expected_size>MAX_BYTES:raise ValueError('音频大小无效或超过200MiB')
            if not isinstance(lrc,str) or len(lrc.encode('utf-8'))>1024*1024:raise ValueError('歌词内容无效或过大')
            self.directory=Path(directory).resolve()
            if not self.directory.is_dir():raise ValueError('请选择已存在的保存文件夹')
            self.stem=safe_stem(stem);self.lrc=lrc;self.expected_size=expected_size
            fd,name=tempfile.mkstemp(prefix='.tianyi-audio-',suffix='.part',dir=self.directory)
            self.part=Path(name);self.file=os.fdopen(fd,'wb')
            request=QNetworkRequest(QUrl(url))
            request.setRawHeader(b'Accept',b'audio/*, application/octet-stream;q=0.8')
            request.setRawHeader(b'Accept-Encoding',b'identity')
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute,QNetworkRequest.LoadControl.Manual)
            request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute,QNetworkRequest.LoadControl.Manual)
            self.received=0;self.total=0;self.prefix=b'';self.started=time.monotonic()
            reply=self.manager.get(request);reply.setReadBufferSize(256*1024);self.reply=reply
            reply.metaDataChanged.connect(lambda:self._headers(reply))
            reply.readyRead.connect(lambda:self._read(reply))
            reply.finished.connect(lambda:self._finish(reply))
            self.timer.start(30000)
        except (OSError,ValueError,TypeError):self._fail('无法开始下载：请检查可信音频地址、格式、大小和保存目录')
    def _headers(self,reply):
        if reply is not self.reply:return False
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        if status and status!=200:
            self._fail('音频服务器返回HTTP错误或重定向；未转发凭据或保存响应');return False
        content_type=bytes(reply.rawHeader('Content-Type')).decode('ascii','ignore').lower().split(';')[0].strip()
        if content_type and not (content_type.startswith('audio/') or content_type in ('application/octet-stream','binary/octet-stream','application/ogg')):
            self._fail('服务器返回的不是音频内容；未保存网页或错误消息');return False
        raw_length=bytes(reply.rawHeader('Content-Length'))
        if raw_length:
            try:
                length=int(raw_length)
                if length<0 or length>MAX_BYTES:raise ValueError()
                self.total=length
            except ValueError:self._fail('服务器音频长度无效或超过200MiB');return False
            if self.expected_size and self.total!=self.expected_size:
                self._fail('服务器音频长度与下载信息不一致，请重新获取音源');return False
        return True
    def _read(self,reply):
        if reply is not self.reply or not self._headers(reply):return
        try:
            while reply.bytesAvailable()>0:
                chunk=bytes(reply.read(min(65536,reply.bytesAvailable())))
                self.received+=len(chunk)
                if self.received>MAX_BYTES or time.monotonic()-self.started>600:raise ValueError('下载超过大小或10分钟时限')
                if len(self.prefix)<4096:self.prefix=(self.prefix+chunk)[:4096]
                self.file.write(chunk)
            self.timer.start(30000);self.progress.emit(self.received,self.total)
        except (OSError,ValueError):self._fail('下载写入失败或超过200MiB／10分钟限制，临时文件已清理')
    def _finish(self,reply):
        if reply is not self.reply:return
        self._read(reply)
        if reply is not self.reply:return
        try:
            if reply.error()!=QNetworkReply.NetworkError.NoError:raise ValueError('网络中断')
            if reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)!=200:raise ValueError('服务器拒绝音频')
            if not self.received or (self.total and self.received!=self.total) or (self.expected_size and self.received!=self.expected_size):raise ValueError('音频长度不完整')
            extension=audio_extension(self.prefix)
            self.file.flush();os.fsync(self.file.fileno());self.file.close();self.file=None
            self.timer.stop()
            target=self.directory/f'{self.stem}.{extension}'
            candidates=[target]+([target.with_suffix('.lrc')] if self.lrc.strip() else [])
            conflicts=[path for path in candidates if path.exists()]
            overwrite=False
            if conflicts and self.resolve_conflict:
                part=self.part
                decision=self.resolve_conflict(conflicts)
                # A modal prompt can process account changes or cancellation.
                if self.reply is not reply or self.part!=part:return
                if decision!='overwrite':
                    self._cleanup();self.skipped.emit();return
                overwrite=True
            audio=_commit(self.part,self.directory,self.stem,extension,paired_lrc=bool(self.lrc.strip()),overwrite=overwrite);self.part=None
        except (OSError,ValueError):self._fail('音频下载未完成或返回内容不是支持的音频；已清理临时文件');return
        self.reply=None;self.timer.stop();reply.deleteLater()
        lrc_path=''
        if self.lrc.strip():
            try:
                # An audio filename may be uniquely suffixed. Keep its exact stem for lyrics.
                target=audio.with_suffix('.lrc')
                if target.exists() and not overwrite:raise FileExistsError()
                lrc_path=export_lrc(self.directory,audio.stem,self.lrc,overwrite=overwrite)
                if Path(lrc_path)!=target:
                    # Racing writer acquired the same lyric name; no mismatched sidecar.
                    Path(lrc_path).unlink(missing_ok=True);lrc_path='';raise FileExistsError()
            except (OSError,ValueError):self.warning.emit('音频已保存，但同名歌词未能保存；请单独导出歌词')
        self.completed.emit(str(audio),lrc_path)
    def _cleanup(self):
        self.timer.stop()
        reply,self.reply=self.reply,None
        if reply is not None:reply.abort();reply.deleteLater()
        if self.file is not None:
            try:self.file.close()
            except OSError:pass
            self.file=None
        if self.part is not None:
            try:self.part.unlink(missing_ok=True)
            except OSError:pass
            self.part=None
    def cancel(self):self._cleanup()
    def _fail(self,message):self._cleanup();self.failed.emit(message)
