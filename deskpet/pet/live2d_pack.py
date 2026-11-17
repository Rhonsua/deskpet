"""Bounded, data-only external Live2D packs; no executable pack extensions."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

ACTIVITIES = frozenset(('idle', 'listen', 'sing', 'turn', 'happy', 'level_up',
    'lift', 'land', 'poke', 'eat', 'sleep', 'phone', 'head_rub', 'mouse_wave'))


@dataclass(frozen=True)
class Live2DSpec:
    root: Path
    scale: float = 1.0
    feet: tuple = (.5, .9)
    head: tuple = (.33, .08, .34, .25)
    pose_heads: dict = field(default_factory=dict)
    pose_scale: dict = field(default_factory=dict)
    hands: tuple = ((.28, .55), (.72, .55))

    def head_for(self, activity):
        return self.pose_heads.get(activity, self.head)

    def scale_for(self, activity):
        return self.scale * self.pose_scale.get(activity, 1.0)


def _inside(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('Live2D 资源需要角色目录内的相对路径')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Live2D 资源路径不能越过角色目录')
    return path


def _json(path, limit=1024*1024):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Live2D 配置缺失或超过大小限制：' + path.name)
    try:
        result = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, RecursionError) as error:
        raise ValueError('Live2D 配置需要有效的 UTF-8 JSON') from error
    if not isinstance(result, dict):
        raise ValueError('Live2D 配置必须为 JSON 对象')
    return result


def _number(value, low, high):
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def _coords(value, count):
    if (not isinstance(value, (list, tuple)) or len(value) != count or
            any(not _number(v, 0, 1) for v in value)):
        raise ValueError('Live2D 显示坐标需要 0～1 的有限数值')
    if count == 4 and (value[2] <= 0 or value[3] <= 0 or
                      value[0]+value[2] > 1 or value[1]+value[3] > 1):
        raise ValueError('Live2D 头部区域必须位于画布内')
    return tuple(value)


def read_live2d_spec(pack_root, data):
    if not isinstance(data, dict) or set(data) - {'directory', 'scale', 'feet', 'head', 'pose_heads', 'pose_scale', 'hands'}:
        raise ValueError('live2d 包含未知设置')
    root = _inside(Path(pack_root).resolve(), data.get('directory'))
    scale = data.get('scale', 1.0)
    if not _number(scale, .25, 2):
        raise ValueError('Live2D scale 需要 0.25～2')
    pose_heads, pose_scale = data.get('pose_heads', {}), data.get('pose_scale', {})
    if (not isinstance(pose_heads, dict) or not isinstance(pose_scale, dict)
            or (set(pose_heads) | set(pose_scale)) - ACTIVITIES):
        raise ValueError('Live2D 姿势显示设置需要约定的动作名称')
    if any(not _number(v, .5, 2) or scale*v > 2 for v in pose_scale.values()):
        raise ValueError('Live2D 姿势倍率需要 0.5～2，合计倍率不能超过 2')
    hands = data.get('hands', ((.28, .55), (.72, .55)))
    if not isinstance(hands, (list, tuple)) or not 1 <= len(hands) <= 4:
        raise ValueError('Live2D hands 需要 1～4 个手部坐标')
    spec = Live2DSpec(root, float(scale), _coords(data.get('feet', (.5, .9)), 2),
                      _coords(data.get('head', (.33, .08, .34, .25)), 4),
                      {key:_coords(value, 4) for key,value in pose_heads.items()},
                      dict(pose_scale), tuple(_coords(value, 2) for value in hands))
    validate_model_files(root)
    return spec


def validate_model_files(root):
    """Validate every resource passed to the native loader before constructing it."""
    root = Path(root).resolve()
    mapping = _json(root/'action-map.json', 65536)
    if type(mapping.get('schemaVersion')) is not int or mapping['schemaVersion'] != 1 or mapping.get('profile') != 'character':
        raise ValueError('外部 Live2D 需要 schemaVersion 1 和 profile character')
    if not _number(mapping.get('renderScale', 1), .25, 1):
        raise ValueError('Live2D renderScale 需要 0.25～1')
    model_path = _inside(root, mapping.get('model'))
    if not model_path.name.endswith('.model3.json'):
        raise ValueError('Live2D model 需要 .model3.json 文件')
    model = _json(model_path, 65536)
    refs = model.get('FileReferences')
    if model.get('Version') != 3 or not isinstance(refs, dict):
        raise ValueError('Live2D 需要 Cubism 3 运行格式')
    if set(refs) - {'Moc', 'Textures', 'DisplayInfo', 'Motions', 'Expressions', 'Physics', 'Pose', 'UserData'}:
        raise ValueError('Live2D FileReferences 包含未知资源类型')
    files = set()
    def resource(value, suffixes, limit):
        path = _inside(root, value)
        if path.suffix.lower() not in suffixes or not path.is_file() or path.stat().st_size > limit:
            raise ValueError('Live2D 资源缺失、类型不符或过大：' + path.name)
        files.add(path)
        return path
    moc = resource(refs.get('Moc'), {'.moc3'}, 64*1024*1024)
    with moc.open('rb') as file:
        if file.read(4) != b'MOC3':
            raise ValueError('Live2D MOC3 文件头无效')
    textures = refs.get('Textures')
    if not isinstance(textures, list) or not 1 <= len(textures) <= 8:
        raise ValueError('Live2D 需要 1～8 张纹理')
    pixels = 0
    for value in textures:
        path = resource(value, {'.png'}, 16*1024*1024)
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path)); size = reader.size()
        if bytes(reader.format()) != b'png' or not (0 < size.width() <= 4096 and 0 < size.height() <= 4096):
            raise ValueError('Live2D 纹理需要最大 4096×4096 的 PNG')
        pixels += size.width() * size.height()
    if pixels > 32*1024*1024:
        raise ValueError('Live2D 纹理合计不能超过 3200 万像素')
    for key in ('DisplayInfo', 'Physics', 'Pose', 'UserData'):
        if key in refs:
            _json(resource(refs[key], {'.json'}, 1024*1024))
    expressions = refs.get('Expressions', [])
    if not isinstance(expressions, list) or len(expressions) > 64:
        raise ValueError('Live2D Expressions 格式无效')
    for item in expressions:
        if not isinstance(item, dict):raise ValueError('Live2D 表情格式无效')
        _json(resource(item.get('File'), {'.json'}, 1024*1024))
    motions = refs.get('Motions')
    activities = mapping.get('activities')
    reset = mapping.get('integrationRules', {}).get('resetParameters') if isinstance(mapping.get('integrationRules'), dict) else None
    if (not isinstance(motions, dict) or not 1 <= len(motions) <= 64 or 'Idle' not in motions
            or not isinstance(activities, dict) or 'idle' not in activities
            or set(activities) - ACTIVITIES or any(not isinstance(v, str) or v not in motions for v in activities.values())
            or not isinstance(reset, dict) or not reset or len(reset) > 256
            or any(not isinstance(k, str) or not 1 <= len(k) <= 80 or not _number(v, -1e6, 1e6) for k,v in reset.items())):
        raise ValueError('Live2D 动作映射或参数复位表无效')
    groups = mapping.get('poseGroups')
    if (not isinstance(groups, list) or len(groups)>32 or any(not isinstance(g,list) or not 1<=len(g)<=32
            or any(not isinstance(p,str) or not 1<=len(p)<=80 for p in g) for g in groups)):
        raise ValueError('Live2D 姿态组无效')
    pose_parts = {part for group in groups for part in group}
    from deskpet.animation.live2d_motion import Curve
    for entries in motions.values():
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise ValueError('每个 Live2D 动作组需要一条动作引用')
        motion = _json(resource(entries[0].get('File'), {'.json'}, 1024*1024))
        meta, curves = motion.get('Meta'), motion.get('Curves')
        if (not isinstance(meta, dict) or not _number(meta.get('Duration'), .01, 600)
                or type(meta.get('Loop')) is not bool or not isinstance(curves,list) or len(curves)>256):
            raise ValueError('Live2D 动作时长或曲线格式无效')
        part_tracks = set()
        tracks = set()
        for c in curves:
            if not isinstance(c,dict):raise ValueError('Live2D 曲线无效')
            seg, target, key = c.get('Segments'), c.get('Target'), c.get('Id')
            if (target not in ('Parameter','PartOpacity') or not isinstance(key,str)
                    or (target=='Parameter' and key not in reset) or not isinstance(seg,list)
                    or not 2<=len(seg)<=16000 or any(not _number(v,-1e6,1e6) for v in seg)):
                raise ValueError('Live2D 曲线需为已声明参数或部件的有限数值')
            if not 1 <= len(key) <= 80 or (target, key) in tracks:
                raise ValueError('Live2D 曲线名称过长或重复')
            tracks.add((target, key))
            if target == 'PartOpacity':
                part_tracks.add(key)
            try:
                curve=Curve(seg)
                if curve.times[0]!=0 or curve.times[-1]>meta['Duration']+1e-5:
                    raise ValueError('动作曲线超出时长')
                if target == 'PartOpacity' and (key not in pose_parts or
                        any(not 0 <= v <= 1 for v in curve.values) or
                        any(control is not None and not (0 <= control[1] <= 1 and 0 <= control[3] <= 1)
                            for control in curve.controls)):
                    raise ValueError('部件透明度须为 0～1 且登记在姿态组')
            except (ValueError,IndexError,TypeError) as error:
                raise ValueError('Live2D 动作曲线无效') from error
        if part_tracks != pose_parts:
            raise ValueError('每个 Live2D 动作必须完整声明姿态部件显隐，避免切换残留')
    if len(files)>160 or sum(p.stat().st_size for p in files)>128*1024*1024:
        raise ValueError('Live2D 运行资源合计不能超过 128 MiB 或 160 个文件')
