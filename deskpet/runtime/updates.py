"""Public GitHub release checks and verified installer downloads (no GUI)."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from deskpet.version import VERSION


REPOSITORY = 'Rhonsua/deskpet'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_INSTALLER_SIZE = 2 * 1024 ** 3
DOWNLOAD_HOSTS = {'api.github.com', 'github.com',
                  'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


class UpdateError(ValueError):
    pass


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    notes: str
    filename: str
    download_url: str
    size: int
    sha256: str = ''
    checksums_url: str = ''


def version_number(value):
    """Stable releases only; compare numbers, never version strings."""
    if not isinstance(value, str) or not re.fullmatch(r'v?(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise UpdateError('发行版标签应为 v主版本.次版本.修订号，例如 v0.6.2。')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


def parse_release(data, current=VERSION):
    if not isinstance(data, dict):
        raise UpdateError('GitHub 返回的版本信息不完整，请稍后重试。')
    if data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    number = version_number(tag)
    if number <= version_number(current):
        return None
    version = '.'.join(map(str, number))
    filename = f'TianyiPet-{version}-Setup.exe'
    base = f'{RELEASES_URL}/download/{tag}/'
    assets = data.get('assets')
    if not isinstance(assets, list):
        raise UpdateError('新版尚未提供 Windows 安装包，可前往发行页查看。')
    candidates = [asset for asset in assets if isinstance(asset, dict)
                  and asset.get('name') == filename and asset.get('state') == 'uploaded']
    if len(candidates) != 1:
        raise UpdateError(f'新版尚未提供 {filename}，可前往发行页查看。')
    asset = candidates[0]
    size = asset.get('size')
    if type(size) is not int or not 1 <= size <= MAX_INSTALLER_SIZE:
        raise UpdateError('新版安装包大小无效，未下载。')
    if asset.get('browser_download_url') != base + filename:
        raise UpdateError('安装包链接不属于本项目的这一发行版，未下载。')
    digest = asset.get('digest') or ''
    checksum = ''
    if digest:
        if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
            raise UpdateError('安装包校验信息无效，未下载。')
        checksum = digest[7:].lower()
    checksum_url = next((base + 'SHA256SUMS.txt' for item in assets
                         if isinstance(item, dict) and item.get('name') == 'SHA256SUMS.txt'
                         and item.get('state') == 'uploaded'
                         and item.get('browser_download_url') == base + 'SHA256SUMS.txt'), '')
    notes = data.get('body') or '本次发行未填写更新公告。'
    if not isinstance(notes, str):
        notes = '本次发行未填写更新公告。'
    return Release(version, f'{RELEASES_URL}/tag/{tag}', notes[:16000], filename,
                   base + filename, size, checksum, checksum_url)


def allowed_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in DOWNLOAD_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise UpdateError('下载链接跳转到了非 GitHub 地址，已停止。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url, *, api=False):
    if not allowed_url(url):
        raise UpdateError('更新地址无效。')
    headers = {'User-Agent': f'TianyiPet/{VERSION}',
               'Accept': 'application/vnd.github+json' if api else 'application/octet-stream'}
    if api:
        headers['X-GitHub-Api-Version'] = '2022-11-28'
    return build_opener(GitHubRedirect()).open(Request(url, headers=headers), timeout=20)


def network_error(error):
    if isinstance(error, HTTPError) and error.code in (403, 429):
        return UpdateError('GitHub 暂时限制了请求次数，请稍后再试。')
    return UpdateError('连接 GitHub 失败，请检查网络后重试，也可前往发行页手动下载。')


def read_limited(response, limit, cancel, timeout=30):
    result = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        if cancel.is_set():
            raise Cancelled()
        if time.monotonic() > deadline:
            raise UpdateError('读取更新信息超时，请稍后重试。')
        chunk = response.read(min(65536, limit + 1 - len(result)))
        if not chunk:
            return bytes(result)
        result.extend(chunk)
        if len(result) > limit:
            raise UpdateError('更新信息过大，已停止读取。')


def fetch_latest(cancel, current=VERSION):
    try:
        with open_url(LATEST_URL, api=True) as response:
            data = json.loads(read_limited(response, 1024 * 1024, cancel))
        return parse_release(data, current)
    except HTTPError as error:
        if error.code == 404:
            return None  # The public repository has no published full release yet.
        raise network_error(error) from None
    except (URLError, OSError) as error:
        raise network_error(error) from None
    except (json.JSONDecodeError, UnicodeError):
        raise UpdateError('GitHub 返回的版本信息无法读取，请稍后重试。') from None


def checksum_from_text(text, filename):
    found = []
    for line in text.splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line.strip())
        if match and match.group(2) == filename:
            found.append(match.group(1).lower())
    if len(found) != 1:
        raise UpdateError('校验文件中没有唯一对应的安装包记录，未安装。')
    return found[0]


def download_release(release, directory, cancel, progress):
    """A partial or mismatched download is never returned as an installer."""
    checksum = release.sha256
    partial = None
    try:
        if not checksum:
            if not release.checksums_url:
                raise UpdateError('此发行版缺少 SHA-256 校验信息，请前往发行页手动下载。')
            with open_url(release.checksums_url) as response:
                content = read_limited(response, 256 * 1024, cancel).decode('utf-8-sig')
            checksum = checksum_from_text(content, release.filename)
        if cancel.is_set():
            raise Cancelled()
        directory = Path(directory) / release.version
        directory.mkdir(parents=True, exist_ok=True)
        with open_url(release.download_url) as response:
            descriptor, name = tempfile.mkstemp(prefix='download-', suffix='.part', dir=directory)
            partial = Path(name)
            digest = hashlib.sha256()
            total = 0
            deadline = time.monotonic() + 1800
            with os.fdopen(descriptor, 'wb') as target:
                while True:
                    if cancel.is_set():
                        raise Cancelled()
                    if time.monotonic() > deadline:
                        raise UpdateError('下载时间过长，已取消；请稍后重试。')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > release.size:
                        raise UpdateError('安装包大小与发行信息不符，已停止下载。')
                    target.write(chunk)
                    digest.update(chunk)
                    progress(total, release.size)
            if total != release.size or digest.hexdigest() != checksum:
                raise UpdateError('安装包下载不完整或校验未通过，请重新下载。')
        if cancel.is_set():
            raise Cancelled()
        path = directory / release.filename
        os.replace(partial, path)
        partial = None
        return path
    except (HTTPError, URLError) as error:
        raise network_error(error) from None
    except OSError:
        raise UpdateError('下载未完成，请检查网络、磁盘空间和更新目录权限后重试。') from None
    except UnicodeError:
        raise UpdateError('安装包校验文件无法读取，请前往发行页查看。') from None
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
