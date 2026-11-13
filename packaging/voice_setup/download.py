"""Fetch a pinned upstream archive, resuming only verified byte ranges."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen


NAME = 'GPT-SoVITS-v2pro-20250604-nvidia50.7z'
SIZE = 8835144925
SHA256 = '97b4edcd451c42357db7e26e6c1c877ca5d85144fe97beaff6d7005d35bee008'
REVISION = 'c8b61d4f627d1f02e74c1ba158a4844051d2289f'
URL_PATH = f'/lj1995/GPT-SoVITS-windows-package/resolve/{REVISION}/{NAME}?download=true'
SOURCES = tuple('https://' + host + URL_PATH for host in ('huggingface.co', 'hf-mirror.com'))
EXTRACTOR = 'https://github.com/ip7z/7zip/releases/download/26.00/7zr.exe'
EXTRACTOR_SHA = '4bec0bc59836a890a11568b58bd12a3e7b23a683557340562da211b6088058ba'
CHUNK = 16 * 1024**2


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch_tool(directory):
    target = directory / '7zr.exe'
    if target.is_file() and digest(target) == EXTRACTOR_SHA:
        return target
    temp = target.with_suffix('.partial')
    with urlopen(Request(EXTRACTOR, headers={'User-Agent': 'TianyiVoiceSetup'}), timeout=60) as response:
        data = response.read(601089)
    if len(data) != 601088 or hashlib.sha256(data).hexdigest() != EXTRACTOR_SHA:
        raise ValueError('解压工具校验失败，请重试。')
    temp.write_bytes(data)
    temp.replace(target)
    return target


def fetch_archive(directory, progress, *, cancel=None, size=SIZE, checksum=SHA256, sources=SOURCES,
                  chunk_size=CHUNK, name=NAME):
    target = directory / name
    if target.is_file() and target.stat().st_size == size and digest(target) == checksum:
        return target
    part = directory / (name + '.partial')
    journal = directory / (name + '.parts.json')
    count = (size + chunk_size - 1) // chunk_size
    complete = set()
    if part.is_file() and part.stat().st_size == size and journal.is_file():
        try:
            saved = json.loads(journal.read_text())
            if saved['sha256'] == checksum and saved['chunk'] == chunk_size:
                complete = {i for i in saved['done'] if type(i) is int and 0 <= i < count}
        except (ValueError, TypeError, KeyError):
            pass
    if not complete:
        journal.unlink(missing_ok=True)
        with part.open('wb') as stream:
            stream.truncate(size)
    lock = threading.Lock()
    stop = threading.Event()
    received = sum(min(chunk_size, size - i * chunk_size) for i in complete)
    def get(i):
        nonlocal received
        start = i * chunk_size
        end = min(size, start + chunk_size) - 1
        for attempt in range(4):
            if stop.is_set() or (cancel is not None and cancel.is_set()):
                return
            url = sources[attempt % len(sources)]
            url += ('&' if '?' in url else '?') + f'part={start}'
            req = Request(url, headers={'Range': f'bytes={start}-{end}', 'User-Agent': 'TianyiVoiceSetup'})
            try:
                with closing(urlopen(req, timeout=75)) as r:
                    if r.status != 206 or r.getheader('Content-Range') != f'bytes {start}-{end}/{size}':
                        raise ValueError('站点返回的下载区间不正确')
                    block = r.read(end - start + 2)
                    if len(block) != end - start + 1:
                        raise ValueError('下载中断')
                break
            except (ValueError, OSError, HTTPException) as exc:
                if attempt == 3:
                    stop.set()
                    raise RuntimeError(f'下载失败，已保留进度。可重试或选择已下载的官方 7z。{exc}') from exc
                time.sleep(attempt + 1)
        with part.open('r+b') as stream:
            stream.seek(start)
            stream.write(block)
        with lock:
            complete.add(i)
            received += len(block)
            tmp = journal.with_suffix('.tmp')
            tmp.write_text(json.dumps({'sha256': checksum, 'chunk': chunk_size, 'done': sorted(complete)}))
            os.replace(tmp, journal)
            progress(received, size)
    progress(received, size)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(get, [i for i in range(count) if i not in complete]))
    if cancel is not None and cancel.is_set():
        raise InterruptedError('下载已暂停，下次选择同一安装位置即可续传。')
    if len(complete) != count or digest(part) != checksum:
        journal.unlink(missing_ok=True)
        raise ValueError('整包 SHA-256 校验失败，请重新下载。')
    os.replace(part, target)
    journal.unlink(missing_ok=True)
    return target
