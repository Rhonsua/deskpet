"""Normal Bilibili audio extraction and local MP3 conversion, off the GUI thread."""
from http.cookiejar import Cookie
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .bilibili_links import video_url
from .bilibili_account import COOKIE_NAMES


class Cancelled(Exception):
    pass


def check_cancel(stopped):
    if stopped.is_set():
        raise Cancelled()


def set_cookies(jar, header):
    # Account cookies are domain-scoped; never add them to CDN HTTP headers.
    for part in header.split(';'):
        name, separator, value = part.strip().partition('=')
        if separator and name in COOKIE_NAMES and not any(c in value for c in '\r\n\0'):
            jar.set_cookie(Cookie(0, name, value, None, False, '.bilibili.com', True, True,
                                  '/', True, True, None, True, None, None, {}))


class QuietLogger:
    def debug(self, message): pass
    def info(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def make_downloader(folder, cookie, stopped, progress):
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.bilibili import BiliBiliIE

    class CancellableDownloader(YoutubeDL):
        def urlopen(self, request):
            check_cancel(stopped)
            return super().urlopen(request)

    last = [0.0]
    def hook(data):
        check_cancel(stopped)
        now = time.monotonic()
        if now - last[0] < .25 and data.get('status') != 'finished':
            return
        last[0] = now
        done = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
        progress(f'正在下载音轨：{done*100/total:.0f}%' if total else f'正在下载音轨：{done/1048576:.1f} MB')

    ydl = CancellableDownloader({
        'quiet': True, 'no_warnings': True, 'logger': QuietLogger(), 'cachedir': False,
        'noplaylist': True, 'format': 'bestaudio/best', 'socket_timeout': 12,
        'retries': 2, 'fragment_retries': 2, 'skip_unavailable_fragments': False,
        'concurrent_fragment_downloads': 1, 'max_filesize': 1024**3,
        'outtmpl': str(folder / 'audio.%(ext)s'), 'progress_hooks': [hook],
        'windowsfilenames': True, 'overwrites': False,
    }, auto_init=False)
    ydl.add_info_extractor(BiliBiliIE())
    set_cookies(ydl.cookiejar, cookie)
    return ydl


def transcode(source, output, stopped, *, ffmpeg=None):
    if ffmpeg is None:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    check_cancel(stopped)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    # Only a local downloaded file is passed to ffmpeg. No account headers,
    # remote URLs, shell commands, or arbitrary playlist files are accepted.
    command = [str(ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
               '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
               '-vn', '-c:a', 'libmp3lame', '-q:a', '2', '-threads', '2', str(output)]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, creationflags=flags)
    deadline = time.monotonic() + 900
    try:
        while True:
            check_cancel(stopped)
            if time.monotonic() > deadline:
                raise ValueError('音频转换超时，请尝试较短的视频。')
            try:
                _, error = process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise ValueError('音轨无法转换为 MP3；未覆盖已有文件。')
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def validate_mp3(path, duration=0):
    from mutagen.mp3 import MP3
    info = MP3(path).info
    if info.length <= 0 or (duration and info.length < duration - max(3, duration * .02)):
        raise ValueError('下载的音频不完整，未保存为完整歌曲。')


def download_mp3(url, directory, cookie='', stopped=None, progress=None, *, tools_directory=None):
    """Return a staged result; the GUI asks about conflicts before committing it."""
    url = video_url(url)
    directory = Path(directory).resolve(strict=True)
    stopped = stopped or threading.Event()
    progress = progress or (lambda text: None)
    from .audio_converter import ensure_converter
    if tools_directory is None:
        raise ValueError('未指定转换工具保存目录。')
    ffmpeg = ensure_converter(tools_directory, stopped, progress)
    folder = Path(tempfile.mkdtemp(prefix='.tianyi-bilibili-', dir=directory))
    try:
        progress('正在读取视频与分 P 音轨…')
        with make_downloader(folder, cookie, stopped, progress) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or info.get('_type', 'video') != 'video' or info.get('is_live'):
                raise ValueError('请选择一个普通视频或明确的分 P；直播暂不支持。')
            if info.get('has_drm'):
                raise ValueError('该视频没有可直接保存的普通音轨。')
            check_cancel(stopped)
            info = ydl.process_ie_result(info, download=True)
            source = Path(ydl.prepare_filename(info)).resolve()
            if not source.is_relative_to(folder) or not source.is_file():
                raise ValueError('没有取得完整音轨；请确认网页登录后能正常播放此分 P。')
        check_cancel(stopped)
        progress('正在转换为 MP3…')
        output = folder / 'converted.mp3'
        transcode(source, output, stopped, ffmpeg=ffmpeg)
        check_cancel(stopped)
        validate_mp3(output, float(info.get('duration') or 0))
        part = int(parse_qs(urlsplit(url).query).get('p', ['1'])[0])
        return dict(path=str(output), folder=str(folder), title=str(info.get('title') or 'B站音频'),
                    id=urlsplit(url).path.strip('/').split('/')[-1], part=part, url=url)
    except BaseException:
        shutil.rmtree(folder)
        raise


def dispose_result(result, directory):
    """Delete only our generated, direct-child staging folder."""
    folder = Path(result['folder']).resolve()
    if folder.parent != Path(directory).resolve() or not folder.name.startswith('.tianyi-bilibili-'):
        raise ValueError('临时目录不在本次下载位置。')
    shutil.rmtree(folder)


def commit_result(result, directory, *, overwrite=False):
    directory = Path(directory).resolve()
    folder = Path(result['folder']).resolve()
    source = Path(result['path']).resolve()
    if (folder.parent != directory or not folder.name.startswith('.tianyi-bilibili-')
            or source.parent != folder or source.name != 'converted.mp3'):
        raise ValueError('下载文件路径无效。')
    target = target_path(result, directory)
    if overwrite:
        os.replace(source, target)
    else:
        # Atomic no-clobber, also protects a file created during the question.
        if os.name == 'nt':
            os.rename(source, target)
        else:
            os.link(source, target)
            source.unlink()
    return target


def target_path(result, directory):
    from deskpet.music.netease.downloads import safe_stem
    stem = safe_stem(result['title'])[:65] + f' [{result["id"]}-P{result["part"]}]'
    return Path(directory) / (safe_stem(stem) + '.mp3')
