"""Sample authored Cubism tracks using the desktop pet's own activity clock."""
from bisect import bisect_right
import json
from pathlib import Path
import math
from singing_choreography import apply_footwork
from mouse_interactions import apply_mouse_reaction


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

    def group_for(self, activity):
        # The checked singing candidate includes head/body yaw and microphone singing.
        if activity == 'sing':
            return 'SingTurn'
        if activity == 'head_rub':
            return 'Idle'
        if activity == 'mouse_wave':
            return 'Wave'
        return self.mapping['activities'].get(activity, 'Idle')

    def sample(self, activity, seconds):
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
            parameters = apply_footwork(parameters, elapsed)
        parameters = apply_mouse_reaction(parameters, activity, elapsed)
        return parameters, parts
