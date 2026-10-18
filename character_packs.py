"""Draft v1 character descriptors; external packs are validated only on request.

This module does not scan on startup, execute pack code, or activate a character.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

STATES = ('idle', 'blink', 'happy', 'eat', 'lift', 'sleep', 'phone',
          'sing-front', 'sing-left', 'sing-right')
DEFAULT_ANCHORS = {'head': (0.5, 0.28), 'feet': (0.5, 0.98)}


@dataclass(frozen=True)
class CharacterPack:
    identifier: str
    name: str
    author: str
    source: str
    root: Path
    states: dict
    anchors: dict

    def state_path(self, state):
        return self.states.get(state, self.states['idle'])


def builtin_sources(variant):
    """Keep today's built-in artwork behind the same state-to-file convention."""
    root = Path(__file__).resolve().parent / 'assets' / 'character'
    sources = {'idle': root / ('tianyi-simple-v3-costume.png' if variant == 'simple'
                                else 'tianyi-refined-v3-smooth.png')}
    if variant == 'refined':
        sources.update({state: root / 'states' / ('sleep-back.png' if state == 'sleep'
                                                 else state + '.png') for state in STATES[1:]})
    return sources


def _inside(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('素材必须使用角色目录内的相对路径')
    target = (root / value).resolve()
    if not target.is_relative_to(root):
        raise ValueError('素材路径不能越过角色目录（包括符号链接）')
    return target


def read_pack(folder):
    root = Path(folder).resolve()
    manifest = _inside(root, 'character.json')
    if manifest.stat().st_size > 65536:
        raise ValueError('角色配置不能超过 64 KiB')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('角色配置 version 必须为 1')
    identifier = data.get('id', '')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', identifier):
        raise ValueError('角色 id 需为小写字母开头的字母、数字、下划线或短横线')
    metadata = {}
    for field, limit in (('name', 80), ('author', 120), ('source', 500)):
        value = data.get(field, '')
        if not isinstance(value, str) or len(value) > limit or (field == 'name' and not value.strip()):
            raise ValueError('角色 ' + field + ' 格式不正确')
        metadata[field] = value.strip()
    states = data.get('states')
    if not isinstance(states, dict) or 'idle' not in states or any(state not in STATES for state in states):
        raise ValueError('states 必须提供 idle，且只能使用约定的动作名称')
    paths = {}
    for state, value in states.items():
        path = _inside(root, value)
        if path.suffix.lower() != '.png' or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError(state + ' 需要角色目录内不超过 16 MiB 的 PNG 文件')
        paths[state] = path
    anchors = dict(DEFAULT_ANCHORS)
    given = data.get('anchors', {})
    if not isinstance(given, dict) or any(key not in anchors for key in given):
        raise ValueError('anchors 仅支持 head 和 feet')
    for key, pair in given.items():
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(type(number) not in (int, float) or not math.isfinite(number)
                    or not 0 <= number <= 1 for number in pair)):
            raise ValueError('锚点需要两个 0 到 1 的相对坐标')
        anchors[key] = tuple(pair)
    return CharacterPack(identifier, root=root, states=paths, anchors=anchors, **metadata)


def validate_images(pack):
    """Decode only in the manual validator, never on ordinary pet startup."""
    from PySide6.QtGui import QImageReader
    expected = None
    for state, path in pack.states.items():
        reader = QImageReader(str(path))
        size = reader.size()
        if bytes(reader.format()) != b'png' or not (0 < size.width() <= 4096 and 0 < size.height() <= 4096):
            raise ValueError(state + ' 图片必须是最大 4096×4096 的 PNG')
        image = reader.read()
        if image.isNull() or not image.hasAlphaChannel():
            raise ValueError(state + ' 图片解码失败或缺少透明通道')
        if expected is not None and size != expected:
            raise ValueError('所有动作图片需要相同的画布尺寸')
        expected = size


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='校验预备角色包，不启用或切换角色')
    parser.add_argument('folder', help='包含 character.json 的角色目录')
    args = parser.parse_args()
    try:
        pack = read_pack(args.folder)
        validate_images(pack)
    except (ValueError, OSError) as error:
        parser.exit(1, '校验失败：' + str(error) + '\n')
    print('校验通过：' + pack.name + '；未提供的动作将回退到 idle（当前尚未开放角色切换）')
