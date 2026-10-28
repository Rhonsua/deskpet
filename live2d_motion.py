"""Sample authored Cubism tracks using the desktop pet's own activity clock."""
from bisect import bisect_right
from dataclasses import dataclass
import json
from pathlib import Path
import math
from singing_choreography import apply_footwork
from mouse_interactions import apply_mouse_reaction
from music_tools.clock import apply_music_beat, beat_values


@dataclass(frozen=True)
class Live2DWalkSpec:
    """Same timing/travel contract as PNG WalkSpec; stride uses the 384×576 canvas."""
    left: str
    right: str
    cycle_seconds: float
    stride: float


class Curve:
    def __init__(self, segments):
        self.times, self.values, self.kinds = [segments[0]], [segments[1]], []
        index = 2
        while index < len(segments):
            kind, end, value = segments[index:index + 3]
            if kind not in (0, 2, 3):
                raise ValueError('当前动作需要预采样为线性或阶梯曲线')
            if end <= self.times[-1]:
                raise ValueError('Live2D 动作时间必须递增')
            self.kinds.append(kind)
            self.times.append(end)
            self.values.append(value)
            index += 3

    def sample(self, seconds):
        i = bisect_right(self.times, seconds) - 1
        if i < 0:
            return self.values[0]
        if i >= len(self.kinds):
            return self.values[-1]
        if self.kinds[i] == 2:
            return self.values[i]
        if self.kinds[i] == 3:
            return self.values[i + 1]
        fraction = (seconds - self.times[i]) / (self.times[i + 1] - self.times[i])
        return self.values[i] + fraction * (self.values[i + 1] - self.values[i])


class MotionLibrary:
    def __init__(self, root):
        self.root = Path(root)
        self.mapping = json.loads((self.root / 'action-map.json').read_text(encoding='utf-8'))
        model = json.loads((self.root / self.mapping['model']).read_text(encoding='utf-8'))
        self.references = model['FileReferences']['Motions']
        self.cache = {}
        self.walk_spec = None
        self.walk_error = ''
        if 'walk' in self.mapping:
            try:
                self.walk_spec = self.read_walk_spec(self.mapping['walk'])
            except (ValueError, KeyError, TypeError, IndexError, OSError, OverflowError) as error:
                # A missing optional motion must not break the established model.
                self.walk_error = '散步动作未启用：' + str(error)

    def read_walk_spec(self, data):
        if not isinstance(data, dict) or set(data) != {'left', 'right', 'stride'}:
            raise ValueError('Live2D walk 需要 left、right 动作组名称及 stride')
        stride = data['stride']
        if type(stride) not in (int, float) or not 1 <= stride <= 4096 or not math.isfinite(stride):
            raise ValueError('散步 stride 需要 1～4096 的有限数值')
        durations = []
        reset = self.mapping['integrationRules']['resetParameters']
        pose_parts = {part for group in self.mapping['poseGroups'] for part in group}
        for direction in ('left', 'right'):
            group = data[direction]
            if not isinstance(group, str) or group not in self.references or group == 'Idle':
                raise ValueError('散步必须提供左右专用动作组')
            relative = self.references[group][0]['File']
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root.resolve()):
                raise ValueError('散步动作路径不能越过模型目录')
            motion = json.loads(path.read_text(encoding='utf-8'))
            meta = motion['Meta']
            duration = meta['Duration']
            if (type(duration) not in (int, float) or not .2 <= duration <= 10
                    or not math.isfinite(duration) or meta.get('Loop') is not True):
                raise ValueError('散步动作必须循环，周期为 0.2～10 秒')
            curves = []
            for c in motion['Curves']:
                target, key, segments = c['Target'], c['Id'], c['Segments']
                if (target not in ('Parameter', 'PartOpacity') or not isinstance(key, str)
                        or not isinstance(segments, list) or len(segments) < 2
                        or (len(segments) - 2) % 3
                        or any(type(v) not in (int, float) or not -1e6 <= v <= 1e6
                               or not math.isfinite(v) for v in segments)):
                    raise ValueError('散步曲线需要有效、有限的线性或阶梯数值')
                curve = Curve(segments)
                if curve.times[0] != 0 or curve.times[-1] > duration:
                    raise ValueError('散步曲线必须从 0 开始且不超过循环周期')
                if target == 'PartOpacity' and any(not 0 <= v <= 1 for v in curve.values):
                    raise ValueError('部件透明度必须在 0～1 之间')
                curves.append((target, key, curve))
            parameters = {key for target, key, _ in curves if target == 'Parameter'}
            parts = {key for target, key, _ in curves if target == 'PartOpacity'}
            if not parameters or not parameters <= reset.keys() or not pose_parts <= parts:
                raise ValueError('散步参数必须登记复位默认值，并声明全部姿态部件的显隐')
            if any(type(reset[key]) not in (int, float) or not -1e6 <= reset[key] <= 1e6
                   or not math.isfinite(reset[key]) for key in parameters):
                raise ValueError('散步参数复位值必须是有限数值')
            self.cache[group] = meta, curves
            durations.append(duration)
        if data['left'] == data['right'] or not math.isclose(*durations):
            raise ValueError('左右需要不同动作组，且循环周期相同')
        return Live2DWalkSpec(data['left'], data['right'], durations[0], float(stride))

    def validate_walk_model(self, parameter_ids, part_ids=None):
        if self.walk_spec is not None:
            used = {key for group in (self.walk_spec.left, self.walk_spec.right)
                    for target, key, _ in self.cache[group][1] if target == 'Parameter'}
            parts = {key for group in (self.walk_spec.left, self.walk_spec.right)
                     for target, key, _ in self.cache[group][1] if target == 'PartOpacity'}
            if not used <= set(parameter_ids) or (part_ids is not None and not parts <= set(part_ids)):
                self.walk_spec = None
                self.walk_error = '散步动作未启用：模型缺少步行曲线引用的参数或部件'

    def group_for(self, activity):
        if activity in ('walk-left', 'walk-right') and self.walk_spec is not None:
            return getattr(self.walk_spec, activity[5:])
        # The checked singing candidate includes head/body yaw and microphone singing.
        if activity == 'sing':
            return 'SingTurn'
        if activity == 'head_rub':
            return 'Idle'
        if activity == 'mouse_wave':
            return 'Wave'
        return self.mapping['activities'].get(activity, 'Idle')

    def sample(self, activity, seconds, beat=None):
        elapsed = max(0, seconds)
        group = self.group_for(activity)
        if group not in self.cache:
            data = json.loads((self.root / self.references[group][0]['File']).read_text(encoding='utf-8'))
            self.cache[group] = (data['Meta'], [
                (curve['Target'], curve['Id'], Curve(curve['Segments'])) for curve in data['Curves']])
        meta, curves = self.cache[group]
        duration = meta['Duration']
        seconds = max(0, seconds)
        if activity == 'mouse_wave':
            seconds = min(duration, elapsed*duration/2.4)
        seconds = seconds % duration if meta.get('Loop') and duration else min(seconds, duration)
        parameters = dict(self.mapping['integrationRules']['resetParameters'])
        parts = {}
        for target, key, curve in curves:
            if target == 'Parameter':
                parameters[key] = curve.sample(seconds)
            elif target == 'PartOpacity':
                parts[key] = curve.sample(seconds)
        if group == 'SingTurn':
            # Match the PNG singing cycle's front/left/right rhythm, with smooth
            # direction holds and the model's authored head/body yaw endpoints.
            yaw = math.tanh(1.6 * math.sin(seconds * math.tau / 4.8)) / math.tanh(1.6)
            parameters['ParamAngleX'] = 28 * yaw
            parameters['ParamBodyAngleX'] = 10 * yaw
            parameters['ParamAngleZ'] *= .65
            parameters['ParamBodyAngleZ'] *= .7
            parameters = (apply_music_beat(parameters, beat) if activity == 'sing' and beat_values(beat)
                          else apply_footwork(parameters, elapsed))
        parameters = apply_mouse_reaction(parameters, activity, elapsed)
        return parameters, parts
