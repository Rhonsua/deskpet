"""Fail-closed admission of the pinned official approval-capable runtime."""
import json
import os
import shutil
import sys
from pathlib import Path
from deskpet.paths import PROJECT_ROOT

VERSION = '0.2.2-alpha.2'
NODE_VERSION = '24.20.0'
ROOT = PROJECT_ROOT


def runtime_directory(data_root=None):
    if data_root is not None or getattr(sys, 'frozen', False):
        data_root = Path(data_root) if data_root is not None else (
            Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'TianyiPet/TianyiPet')
        return data_root / 'work-runtime' / f'dsh-{VERSION}-node-{NODE_VERSION}-x64'
    return ROOT / 'local-work' / 'harness-npm'


INSTALL = runtime_directory()


def runtime_launch_args(cli, patch):
    """Avoid cmd.exe consuming early stdin while executing the npm batch shim.

    The SDK immediately writes initialize to stdin. Launch the same admitted
    official JS entry directly, with no shell between its JSONL pipes.
    """
    cli = Path(cli)
    entry = cli.parent.parent / '@deepseek-ai/dsh/lib/bin.js'
    bundled_node = cli.parents[2] / 'node/node.exe'
    if not bundled_node.is_file():
        bundled_node = cli.parent / 'node.exe'  # Older local runtime layout.
    node = str(bundled_node) if bundled_node.is_file() else (
        None if getattr(sys, 'frozen', False) else shutil.which('node'))
    if not node or not entry.is_file():
        raise ValueError('工作环境缺少 Node.js 或官方启动文件，请重新安装工作环境。')
    return (node, str(entry), '--profile', 'sdk', '--patch', str(patch))


def runtime_cli(install=None, *, require_marker=True):
    install = Path(install) if install else INSTALL
    try:
        marker = (json.loads((install / 'deskpet-runtime-ready.json').read_text(encoding='utf-8-sig'))
                  if require_marker else {'version': VERSION})
        package = json.loads((install / 'node_modules/@deepseek-ai/dsh/package.json').read_text(encoding='utf-8-sig'))
        cli = install / 'node_modules/.bin/dsh.cmd'
        nested = install / 'node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib'
        server = nested if nested.is_dir() else install / 'node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib'
        sources = '\n'.join(path.read_text(encoding='utf-8-sig') for path in server.rglob('*.js'))
        if (not isinstance(marker, dict) or not isinstance(package, dict)
                or marker.get('version') != VERSION or package.get('version') != VERSION or not cli.is_file()
                or 'approvalRequests' not in sources or 'allowed-once' not in sources):
            raise ValueError('runtime admission failed')
        return cli
    except (OSError, ValueError, TypeError):
        raise ValueError('工作后端尚未准备完整，需要从官方源下载安装。') from None
