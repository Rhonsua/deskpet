"""First-use official runtime setup, outside the replaceable application folder.

Only a fully validated staging directory is published. All heavy work runs in
the console helper; stopping the task also stops npm and leaves sessions alone.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager

from .harness_runtime import VERSION, NODE_VERSION, runtime_cli, runtime_directory, runtime_launch_args

NODE_ARCHIVE = f'node-v{NODE_VERSION}-win-x64.zip'
NODE_URL = f'https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}'
# Published at https://nodejs.org/dist/v24.20.0/SHASUMS256.txt
NODE_SHA256 = '6cac9ffbca8f6a47091e4b5c772e0606049c3871cb67d900c0cedde630e545ba'
REGISTRY = 'https://registry.npmjs.org'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class SetupCancelled(Exception):
    pass


def check_cancel(cancelled):
    if cancelled.is_set():
        raise SetupCancelled('工作已停止。')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download_node(cache, progress, cancelled):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / NODE_ARCHIVE
    if archive.is_file() and file_hash(archive) == NODE_SHA256:
        return archive
    temporary = archive.with_suffix('.zip.partial')
    progress('正在从 Node.js 官方下载运行环境…')
    request = urllib.request.Request(NODE_URL, headers={'User-Agent': 'TianyiPet-runtime-setup'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, temporary.open('wb') as output:
            total = int(response.headers.get('Content-Length', '0'))
            done, last = 0, 0.0
            while True:
                check_cancel(cancelled)
                block = response.read(256 * 1024)
                if not block:
                    break
                output.write(block)
                done += len(block)
                if time.monotonic() - last >= 1:
                    suffix = f' / {total / 1048576:.1f} MB' if total else ' MB'
                    progress(f'正在下载 Node.js：{done / 1048576:.1f}' + suffix)
                    last = time.monotonic()
        check_cancel(cancelled)
        if file_hash(temporary) != NODE_SHA256:
            raise ValueError('Node.js 下载文件校验失败，请重新开始工作以重试。')
        temporary.replace(archive)
        return archive
    finally:
        temporary.unlink(missing_ok=True)


def extract_node(archive, destination, cancelled):
    """Strip exactly the vendor root, rejecting paths/links outside staging."""
    destination = Path(destination).resolve()
    prefix = f'node-v{NODE_VERSION}-win-x64'
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            check_cancel(cancelled)
            path = PurePosixPath(member.filename)
            if (not path.parts or path.parts[0] != prefix or '..' in path.parts
                    or '\\' in member.filename or ':' in member.filename
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('Node.js 压缩包包含无效路径，安装已停止。')
            target = destination.joinpath(*path.parts[1:]).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('Node.js 解压路径无效。')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)


def remove_owned_tree(path, parent):
    """Never recursively remove a session, install root, or redirected tree."""
    path, parent = Path(path), Path(parent).resolve()
    if not path.exists():
        return
    attributes = path.lstat()
    if (path.parent.resolve() != parent or path.resolve() == parent
            or not path.resolve().is_relative_to(parent)
            or getattr(attributes, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('工作环境临时目录不安全，已停止清理。')
    shutil.rmtree(path)


def rename_ready_tree(source, destination):
    # Windows Defender/indexers may briefly hold a newly extracted executable.
    # Retry only the rename, never re-download or publish a partial directory.
    for attempt in range(21):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(.15)


@contextmanager
def install_lock(install, progress, cancelled):
    # OS file locks are released even when the parent kills this worker.
    import msvcrt
    lockfile = install.parent / ('.' + install.name + '.lock')
    with lockfile.open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        announced = False
        deadline = time.monotonic() + 1200
        while True:
            check_cancel(cancelled)
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if not announced:
                    progress('另一窗口正在准备工作环境，等待完成…')
                    announced = True
                if time.monotonic() >= deadline:
                    raise ValueError('另一个窗口仍在准备工作环境，请稍后重试。') from None
                cancelled.wait(.2)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def terminate_tree(process):
    if process.poll() is not None:
        return
    taskkill = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe'
    try:
        subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=8, creationflags=CREATE_NO_WINDOW)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def install_packages(stage, parent, progress, cancelled):
    lock = Path(__file__).with_name('runtime_package_lock.json')
    specification = json.loads(lock.read_text(encoding='utf-8'))
    if specification['packages']['']['dependencies'] != {'@deepseek-ai/dsh': VERSION}:
        raise ValueError('工作环境版本清单不匹配，请更新桌宠。')
    (stage / 'package.json').write_text(json.dumps(specification['packages']['']), encoding='utf-8')
    shutil.copyfile(lock, stage / 'package-lock.json')
    config = stage / '.npmrc'
    config.write_text('registry=' + REGISTRY + '\nstrict-ssl=true\n', encoding='utf-8')
    global_config = stage / 'empty-global.npmrc'
    global_config.write_text('', encoding='utf-8')
    environment = {k: v for k, v in os.environ.items()
                   if not k.lower().startswith('npm_config_')
                   and k.upper() not in ('NODE_OPTIONS', 'NODE_PATH', 'DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL')}
    environment.update(NPM_CONFIG_USERCONFIG=str(config), NPM_CONFIG_GLOBALCONFIG=str(global_config),
                       NPM_CONFIG_CACHE=str(parent / 'npm-cache'), NPM_CONFIG_UPDATE_NOTIFIER='false', CI='true')
    environment['PATH'] = str(stage / 'node') + os.pathsep + environment.get('PATH', '')
    command = [str(stage / 'node/node.exe'), str(stage / 'node/node_modules/npm/bin/npm-cli.js'),
               'ci', '--prefix', str(stage), '--omit=dev', '--include=optional',
               '--registry=' + REGISTRY, '--no-audit', '--no-fund',
               '--fetch-retries=1', '--fetch-timeout=45000']
    progress('正在从官方 npm 源安装 DeepSeek Harness，首次准备可能需要几分钟…')
    started = time.monotonic()
    with (parent / 'setup.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=stage, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
        try:
            while process.poll() is None:
                check_cancel(cancelled)
                elapsed = time.monotonic() - started
                if elapsed > 900:
                    raise ValueError('后端下载超过 15 分钟，请检查网络后重新开始工作。')
                progress(f'正在下载并安装官方后端，已用时 {int(elapsed)} 秒；可以点击“停止工作”取消。')
                cancelled.wait(5)
            check_cancel(cancelled)
            if process.returncode:
                raise ValueError('官方后端安装失败，请检查网络和剩余磁盘空间后重试。安装日志：' + str(parent / 'setup.log'))
        finally:
            terminate_tree(process)


def validate_runtime(install, *, require_marker=True):
    cli = runtime_cli(install, require_marker=require_marker)
    runtime_launch_args(cli, install / 'unused.patch.yml')
    review = install / 'node_modules/@deepseek-ai/dsh-experimental-auto-review/lib/index.js'
    if not review.is_file():
        raise ValueError('工作环境缺少官方审批组件。')
    return cli


def ensure_runtime(install=None, progress=lambda _: None, cancelled=None):
    cancelled = cancelled or threading.Event()
    install = Path(install or runtime_directory()).resolve()
    check_cancel(cancelled)
    try:
        return validate_runtime(install)
    except ValueError:
        pass
    if os.name != 'nt':
        raise ValueError('自动准备工作环境目前仅支持 Windows x64。')
    parent = install.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / (install.name + '.installing')
    previous = parent / (install.name + '.previous')
    with install_lock(install, progress, cancelled):
        try:
            return validate_runtime(install)
        except ValueError:
            pass
        progress('首次使用工作模式，正在自动准备 Node.js 和官方后端；不会修改系统环境。')
        remove_owned_tree(stage, parent)
        stage.mkdir()
        try:
            archive = download_node(parent / 'downloads', progress, cancelled)
            progress('正在解压并验证 Node.js…')
            extract_node(archive, stage / 'node', cancelled)
            install_packages(stage, parent, progress, cancelled)
            check_cancel(cancelled)
            progress('正在检查官方后端与审批组件…')
            validate_runtime(stage, require_marker=False)
            (stage / 'deskpet-runtime-ready.json').write_text(json.dumps({
                'version': VERSION, 'node_version': NODE_VERSION, 'source': REGISTRY,
                'node_sha256': NODE_SHA256}), encoding='utf-8')
            # Each release has its own runtime folder. No session/config path is
            # ever moved or deleted during repair or a later application update.
            remove_owned_tree(previous, parent)
            check_cancel(cancelled)
            if install.exists():
                rename_ready_tree(install, previous)
            try:
                rename_ready_tree(stage, install)
            except OSError:
                if previous.exists() and not install.exists():
                    rename_ready_tree(previous, install)
                raise
            progress('工作环境已准备好，正在继续本次任务…')
            return validate_runtime(install)
        except (urllib.error.URLError, TimeoutError) as error:
            raise ValueError('无法从官方源下载运行环境，请检查网络后重新开始工作。') from error
        finally:
            # A forced stop can leave staging behind; the next try clears only
            # this exact owned staging directory while holding the setup lock.
            remove_owned_tree(stage, parent)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=runtime_directory())
    args = parser.parse_args()
    print(ensure_runtime(args.directory, progress=lambda text: print(text, flush=True)))
