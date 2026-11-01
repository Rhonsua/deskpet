"""Discover metadata, then execute a trusted Python package only on enable.

Install by manually extracting one package directory under mod-packages. Each
package has mod.json and entry.py, exporting factory(context). There is no ZIP
extraction and no sandbox: enabled Python has the application's full access.
No package __init__.py is executed implicitly. Relative imports from entry.py
work inside an isolated namespace, removed when its instance is stopped.

Version 0.4.1 ships no built-in mods. builtin/builtin-* IDs are reserved; any
collision with an already registered host mod is also rejected by register().
"""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import sys
import types
from uuid import uuid4

from .api import ModManifest


_MAX_PACKAGE_BYTES = 16 * 1024 * 1024
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_ENTRIES = 1024


def _inside(path, root):
    resolved = path.resolve()
    resolved.relative_to(root)
    return resolved


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _check_package(directory):
    """Bound file counts/sizes and reject links, including Windows junctions."""
    root = directory.resolve()
    if _linked(directory) or root != directory:
        raise ValueError('包目录路径已更改或使用链接')
    stack = [root]
    entries = 0
    size = 0
    while stack:
        for path in stack.pop().iterdir():
            entries += 1
            if entries > _MAX_ENTRIES or _linked(path):
                raise ValueError('包中文件过多或包含链接')
            path = _inside(path, root)
            if path.is_dir():
                stack.append(path)
            elif path.is_file():
                length = path.stat().st_size
                size += length
                if length > _MAX_FILE_BYTES or size > _MAX_PACKAGE_BYTES:
                    raise ValueError('包文件超过大小限制')
            else:
                raise ValueError('包中包含非普通文件')
    if not (root / 'entry.py').is_file():
        raise ValueError('缺少固定入口entry.py')
    return root


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('元数据字段重复')
        result[key] = value
    return result


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('元数据文本无效')
    value.encode('utf-8')
    return value.strip()


def _manifest(directory):
    path = _inside(directory / 'mod.json', directory)
    with path.open('rb') as file:
        data = file.read(65537)
    if len(data) > 65536:
        raise ValueError('mod.json超过64KiB')
    raw = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique)
    required = {'id', 'name', 'version', 'api_version'}
    if not isinstance(raw, dict) or not required <= set(raw) <= required | {'description'}:
        raise ValueError('元数据字段不符合接口')
    mod_id = _text(raw['id'], 64)
    if re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', mod_id) is None:
        raise ValueError('Mod ID无效')
    if mod_id == 'builtin' or mod_id.startswith(('builtin-', 'builtin_')):
        raise ValueError('Mod ID使用了主程序保留名称')
    version = _text(raw['version'], 50)
    if re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}(?:[-+][a-zA-Z0-9.-]+)?', version) is None:
        raise ValueError('Mod版本号无效')
    if type(raw['api_version']) is not int or raw['api_version'] != 1:
        raise ValueError('不支持的Mod接口版本')
    description = raw.get('description', '')
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError('Mod描述无效')
    description.encode('utf-8')
    return ModManifest(mod_id, _text(raw['name'], 100), version, description, 1)


def _unload(namespace):
    for key in list(sys.modules):
        if key == namespace or key.startswith(namespace + '.'):
            sys.modules.pop(key, None)


class _Instance:
    def __init__(self, mod, namespace):
        self._mod = mod
        self._namespace = namespace
        self._stopped = False

    def start(self):
        return self._call('start')

    def tick(self, now):
        return self._call('tick', now)

    def create_widget(self, parent=None):
        return self._call('create_widget', parent)

    def _call(self, name, *args):
        try:
            return getattr(self._mod, name)(*args)
        except BaseException as error:
            if isinstance(error, Exception):
                raise
            raise RuntimeError('Mod尝试退出生命周期回调') from error

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            return self._call('stop')
        finally:
            _unload(self._namespace)


def _factory(directory, manifest):
    def create(context):
        # Recheck on enable: a manually replaced package must still respect the
        # metadata/path/size contract established at discovery time.
        path = _check_package(directory)
        if _manifest(path) != manifest:
            raise ValueError('Mod包信息已更改，请重启程序重新扫描')
        namespace = '_desktop_pet_package_' + uuid4().hex
        package = types.ModuleType(namespace)
        package.__path__ = [str(path)]
        package.__package__ = namespace
        package.__spec__ = importlib.machinery.ModuleSpec(namespace, loader=None, is_package=True)
        sys.modules[namespace] = package
        try:
            spec = importlib.util.spec_from_file_location(namespace + '.entry', path / 'entry.py')
            if spec is None or spec.loader is None:
                raise ValueError('无法加载Mod入口')
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            factory = getattr(module, 'factory', None)
            if not callable(factory):
                raise ValueError('entry.py需要导出factory(context)')
            mod = factory(context)
            if not all(callable(getattr(mod, name, None)) for name in ('start', 'tick', 'stop', 'create_widget')):
                stop = getattr(mod, 'stop', None)
                if callable(stop):
                    stop()
                raise ValueError('Mod实例缺少生命周期方法')
            return _Instance(mod, namespace)
        except BaseException as error:
            _unload(namespace)
            if isinstance(error, Exception):
                raise
            raise RuntimeError('Mod尝试退出加载过程') from error
    return create


def discover(root):
    """Return ([(ModManifest, lazy_factory)], [short warning messages])."""
    found = []
    warnings = []
    candidates = {}
    try:
        root = Path(root).resolve()
        if not root.exists():
            return [], []
        children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except (OSError, ValueError, RuntimeError):
        return [], ['Mod包目录无法读取。']
    if len(children) > 256:
        return [], ['Mod包目录项目过多（最多256项）。']
    for child in children:
        try:
            if _linked(child):
                raise ValueError('包目录不能使用链接')
            if not child.is_dir():
                continue
            directory = _inside(child, root)
            if not (directory / 'mod.json').exists():
                continue
            directory = _check_package(directory)
            manifest = _manifest(directory)
            candidates.setdefault(manifest.id, []).append((manifest, directory))
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as error:
            warnings.append(f'{child.name[:80]}：Mod包无效（{str(error)[:120]}）。')
    for mod_id, entries in candidates.items():
        if len(entries) != 1:
            warnings.append(f'{mod_id}：多个包使用相同ID，已全部跳过。')
            continue
        manifest, directory = entries[0]
        found.append((manifest, _factory(directory, manifest)))
    return found, warnings
