"""Prepare a pinned converter on first use, outside the replaceable app folder."""
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.error import URLError
import zipfile

WHEEL_URL = ('https://files.pythonhosted.org/packages/2c/c6/'
             'fa760e12a2483469e2bf5058c5faff664acf66cadb4df2ad6205b016a73d/'
             'imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl')
WHEEL_HASH = '02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a'
BINARY_NAME = 'ffmpeg-win-x86_64-v7.1.exe'
BINARY_HASH = '2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3'


def file_hash(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def ensure_converter(directory, stopped, progress):
    try:
        return _ensure_converter(directory, stopped, progress)
    except URLError as exc:
        raise ValueError('MP3 转换工具下载失败，请检查网络后重试；已有歌曲不受影响。') from exc


def _ensure_converter(directory, stopped, progress):
    from .bilibili_download import check_cancel
    check_cancel(stopped)
    # Development setups may already have this converter; never copy it again.
    if not getattr(sys, 'frozen', False):
        try:
            import imageio_ffmpeg
            return Path(imageio_ffmpeg.get_ffmpeg_exe())
        except (ImportError, RuntimeError):
            pass
    system = shutil.which('ffmpeg')
    if system:
        return Path(system)
    cache = Path(directory) / 'audio-converter' / '7.1'
    executable = cache / BINARY_NAME
    check_cancel(stopped)
    if executable.is_file() and file_hash(executable) == BINARY_HASH:
        return executable
    if os.name != 'nt':
        raise ValueError('请安装 ffmpeg 后重试。')
    cache.mkdir(parents=True, exist_ok=True)
    progress('首次使用：正在准备 MP3 转换工具（约 30 MB 下载，仅需一次）…')
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=cache) as folder:
        wheel = Path(folder) / 'converter.whl'
        with urlopen(WHEEL_URL, timeout=15) as response, wheel.open('wb') as output:
            total, last = 0, 0.0
            while True:
                check_cancel(stopped)
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 40 * 1024**2:
                    raise ValueError('转换工具下载内容异常。')
                output.write(chunk)
                if time.monotonic() - last > .5:
                    progress(f'首次准备转换工具：{total/1048576:.1f} / 29.8 MB')
                    last = time.monotonic()
        check_cancel(stopped)
        if file_hash(wheel) != WHEEL_HASH:
            raise ValueError('转换工具下载校验失败，请重试。')
        candidate = Path(folder) / BINARY_NAME
        with zipfile.ZipFile(wheel) as archive:
            with archive.open('imageio_ffmpeg/binaries/' + BINARY_NAME) as source, candidate.open('wb') as output:
                shutil.copyfileobj(source, output)
            # Preserve the wheel's license notices; no package installer needed.
            for name in archive.namelist():
                if 'license' in name.lower() and not name.endswith('/'):
                    (cache / Path(name).name).write_bytes(archive.read(name))
        check_cancel(stopped)
        if file_hash(candidate) != BINARY_HASH:
            raise ValueError('转换工具解压校验失败，请重试。')
        os.replace(candidate, executable)
    return executable
