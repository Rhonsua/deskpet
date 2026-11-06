"""Resolve local voice paths without loading model code or user chat data."""
import json
from pathlib import Path


def speech_paths(settings, project_root, data_dir=None):
    base = Path(project_root) / 'local-work' / 'tianyi-tts'
    default = base / 'speech-config.json'
    selected = settings.value('speech/config', '')
    if data_dir is not None and (not selected or
            (Path(selected).suffix.lower() == '.zip' and not Path(selected).is_file())):
        from .packs import PACK_FOLDER, available_packs
        try:
            selected = next(iter(available_packs(Path(data_dir) / PACK_FOLDER)), None)
        except OSError:
            selected = None
    config = str(selected or default)
    manifest_path = default if Path(config).suffix.lower() == '.zip' else Path(config)
    manifest = {}
    try:
        value = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        if isinstance(value, dict):
            manifest = value
    except (OSError, ValueError, UnicodeError):
        pass
    def resolve(name, field, fallback):
        saved = str(settings.value('speech/' + name, '') or '').strip()
        if saved:
            return saved
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            return str(fallback)
        path = Path(value)
        return str(path if path.is_absolute() else manifest_path.parent / path)
    return (resolve('python', 'python', base / 'runtime' / 'Scripts' / 'python.exe'),
            resolve('engine', 'engine_root', base / 'GPT-SoVITS'), config)


def missing_paths(values):
    missing = []
    for name, value, directory in zip(('语音运行环境', '语音引擎', '声音配置'), values, (False, True, False)):
        value = str(value or '').strip()
        try:
            exists = bool(value) and (Path(value).is_dir() if directory else Path(value).is_file())
        except (OSError, ValueError):
            exists = False
        if not exists:
            missing.append(name)
    return missing


def installation_status(values):
    missing = missing_paths(values)
    return ('尚未找到：' + '、'.join(missing) + '。请展开高级设置检查路径。' if missing else
            '已找到本机语音环境和声音配置；启用后会加载模型，实际可用状态以准备结果为准。')


def speech_volume(settings):
    try:
        return max(0, min(100, int(settings.value('speech/volume', 100))))
    except (TypeError, ValueError):
        return 100
