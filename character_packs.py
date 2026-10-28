"""Data-only PNG character packs, discovered on request and decoded on selection."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import hashlib
import os
import sys

STATES = ('idle', 'blink', 'happy', 'eat', 'lift', 'sleep', 'phone',
          'sing-front', 'sing-left', 'sing-right')
DEFAULT_ANCHORS = {'head': (0.5, 0.28), 'feet': (0.5, 0.98)}


@dataclass(frozen=True)
class WalkSpec:
    """One dual-step loop; stride is travel in source-canvas pixels per loop.

    Movement consumes cycle_seconds/stride, independently of PNG or Live2D.
    PNG sequences retain their full canvas and share the character's anchors.
    """
    left: tuple
    right: tuple
    fps: float
    stride: float

    @property
    def frame_count(self):
        return len(self.left)

    @property
    def cycle_seconds(self):
        return self.frame_count / self.fps

    def frame_key(self, direction, elapsed):
        if direction not in ('left', 'right', -1, 1):
            raise ValueError('散步方向必须为 left/right 或 -1/1')
        side = 'left' if direction in ('left', -1) else 'right'
        index = int(max(0.0, elapsed) * self.fps) % self.frame_count
        return f'walk-{side}:{index}'

    def image_paths(self):
        return {f'walk-{side}:{index}': path
                for side in ('left', 'right')
                for index, path in enumerate(getattr(self, side))}


@dataclass(frozen=True)
class CharacterPack:
    identifier: str
    name: str
    author: str
    source: str
    root: Path
    states: dict
    anchors: dict
    singing_hem: float | None = None
    walk: WalkSpec | None = None

    def state_path(self, state):
        if state in ('sing-left', 'sing-right') and state not in self.states:
            return self.states.get('sing-front', self.states['idle'])
        return self.states.get(state, self.states['idle'])


def character_directory():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TianyiPet' / 'characters'
    return Path(__file__).resolve().parent / 'characters'


def selected_folder(root, selection):
    if not isinstance(selection, str) or not selection.startswith('external:'):
        raise ValueError('无效的角色选择')
    folder = selection[len('external:'):]
    if not folder or folder in ('.', '..') or any(c in folder for c in '/\\:'):
        raise ValueError('角色必须放在角色目录的直接子文件夹内')
    return _inside(Path(root).resolve(), folder)


def discover_packs(root):
    """Read small descriptors only; invalid packs cannot hide the good ones."""
    root = Path(root).resolve()
    if not root.exists():
        return {}, []
    packs, errors = {}, []
    for folder in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if folder.name.startswith('.') or not folder.is_dir():
            continue
        if not (folder / 'character.json').exists() and not (folder / 'idle.png').exists():
            continue
        if len(packs) + len(errors) >= 128:
            errors.append('最多扫描 128 个角色包，请移走不使用的角色文件夹')
            break
        selection = 'external:' + folder.name
        try:
            pack = read_pack(selected_folder(root, selection))
            packs[selection] = pack
        except (ValueError, OSError) as error:
            errors.append(folder.name + '：' + str(error))
    return packs, errors


def builtin_sources(variant):
    """Keep today's built-in artwork behind the same state-to-file convention."""
    root = Path(__file__).resolve().parent / 'assets' / 'character'
    # Legacy simple selections resolve to the remaining static character.
    sources = {'idle': root / 'tianyi-refined-v3-smooth.png'}
    sources.update({state: root / 'states' / ('sleep-back.png' if state == 'sleep'
                                             else state + '.png') for state in STATES[1:]})
    return sources


def builtin_walk():
    """Optional built-in PNG loop; absence advertises no walking capability."""
    root = Path(__file__).resolve().parent / 'assets' / 'character' / 'walk'
    manifest = root / 'walk.json'
    if not manifest.is_file():
        return None
    if manifest.stat().st_size > 65536:
        raise ValueError('散步配置不能超过 64 KiB')
    try:
        data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    except (ValueError, RecursionError) as error:
        raise ValueError('walk.json 需要有效的 UTF-8 JSON 配置') from error
    return read_walk_spec(root, data)


def read_walk_spec(root, data):
    """Validate an explicitly declared loop without decoding during discovery."""
    root = Path(root).resolve()
    if (not isinstance(data, dict) or set(data) != {'left', 'right', 'fps', 'stride'}):
        raise ValueError('walk 必须且只能包含 left、right、fps、stride')
    for key, low, high in (('fps', 1, 30), ('stride', 1, 4096)):
        value = data[key]
        if (type(value) not in (int, float) or not low <= value <= high
                or not math.isfinite(value)):
            raise ValueError(f'walk.{key} 需要 {low} 到 {high} 的有限数值')
    sequences = {}
    for side in ('left', 'right'):
        values = data[side]
        if not isinstance(values, list) or not 2 <= len(values) <= 48:
            raise ValueError('walk.' + side + ' 需要按播放顺序列出 2 到 48 张 PNG')
        paths = []
        for value in values:
            path = _inside(root, value)
            if path.suffix.lower() != '.png' or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('walk.' + side + ' 需要角色目录内不超过 16 MiB 的 PNG 文件')
            paths.append(path)
        if len(set(paths)) < 2:
            raise ValueError('每个散步方向至少需要两张不同的帧文件，不能用单张站姿滑行')
        sequences[side] = tuple(paths)
    if len(sequences['left']) != len(sequences['right']):
        raise ValueError('左右散步序列的帧数必须一致，以共用步频和步幅')
    return WalkSpec(fps=float(data['fps']), stride=float(data['stride']), **sequences)


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
    if manifest.exists():
        if manifest.stat().st_size > 65536:
            raise ValueError('角色配置不能超过 64 KiB')
        try:
            data = json.loads(manifest.read_text(encoding='utf-8-sig'))
        except (ValueError, RecursionError) as error:
            raise ValueError('character.json 需要有效的 UTF-8 JSON 配置') from error
    else:
        identifier = root.name if re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', root.name) else (
            'pet-' + hashlib.sha256(root.name.encode('utf-8')).hexdigest()[:12])
        data = {'version': 1, 'id': identifier, 'name': root.name,
                'states': {state: state + '.png' for state in STATES
                           if (root / (state + '.png')).is_file()}}
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
    if anchors['head'][1] >= anchors['feet'][1]:
        raise ValueError('head 锚点应在 feet 锚点上方')
    singing = data.get('singing_motion', {})
    if not isinstance(singing, dict) or any(key not in ('legs', 'hem') for key in singing):
        raise ValueError('singing_motion 仅支持 legs 和 hem')
    legs, hem = singing.get('legs', False), singing.get('hem', 0.64)
    if type(legs) is not bool:
        raise ValueError('singing_motion.legs 必须为 true 或 false')
    if type(hem) not in (int, float) or not 0.35 <= hem <= 0.90 or not math.isfinite(hem):
        raise ValueError('singing_motion.hem 需要 0.35 到 0.90 的画布高度比例')
    if legs and 'sing-front' not in paths:
        raise ValueError('启用唱歌腿部动画需要声明 sing-front 图片')
    return CharacterPack(identifier, root=root, states=paths, anchors=anchors,
                         singing_hem=float(hem) if legs else None,
                         walk=read_walk_spec(root, data['walk']) if 'walk' in data else None,
                         **metadata)


def validate_images(pack):
    """Return decoded images, with a shared 16-megapixel allocation budget."""
    paths = dict(pack.states)
    if pack.walk is not None:
        paths.update(pack.walk.image_paths())
    return _validate_image_paths(paths)


def validate_walk_images(walk):
    """Decode a standalone built-in loop, preserving its common full canvas."""
    return _validate_image_paths(walk.image_paths()) if walk is not None else {}


def _validate_image_paths(paths):
    from PySide6.QtGui import QImageReader, QImage
    expected = None
    decoded, images, pixels = {}, {}, 0
    for state, path in paths.items():
        if path in decoded:
            images[state] = decoded[path]
            continue
        reader = QImageReader(str(path))
        size = reader.size()
        if bytes(reader.format()) != b'png' or not (0 < size.width() <= 4096 and 0 < size.height() <= 4096):
            raise ValueError(state + ' 图片必须是最大 4096×4096 的 PNG')
        pixels += size.width() * size.height()
        if pixels > 16 * 1024 * 1024:
            raise ValueError('角色包图片合计不能超过 1600 万像素，请缩小画布或减少图片')
        if expected is not None and size != expected:
            raise ValueError('所有动作图片需要相同的画布尺寸')
        image = reader.read()
        if image.isNull() or not image.hasAlphaChannel():
            raise ValueError(state + ' 图片解码失败或缺少透明通道')
        alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
        values, stride = bytes(alpha.constBits()), alpha.bytesPerLine()
        visible = transparent = False
        for y in range(alpha.height()):
            row = values[y * stride:y * stride + alpha.width()]
            visible = visible or any(row)
            transparent = transparent or row.count(255) < len(row)
            if visible and transparent:
                break
        if not visible or not transparent:
            raise ValueError(state + ' 需要同时包含可见角色和透明区域，不能是空白或完全不透明图片')
        expected = size
        decoded[path] = images[state] = image
    return images


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='校验角色配置、PNG 图片及画布尺寸')
    parser.add_argument('folder', help='包含 idle.png 或 character.json 的角色目录')
    args = parser.parse_args()
    try:
        pack = read_pack(args.folder)
        validate_images(pack)
    except (ValueError, OSError) as error:
        parser.exit(1, '校验失败：' + str(error) + '\n')
    print('校验通过：' + pack.name + '；可在桌宠设置中刷新并切换角色')
