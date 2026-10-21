"""Nearby pointer attention, independent of drag gestures and authored motions."""
import math


class PointerFollow:
    def __init__(self):
        self.x = self.y = self.weight = 0.0

    def step(self, dx, dy, seconds, *, enabled=True, scale=1):
        distance = math.hypot(dx, dy) / scale
        proximity = max(0, min(1, (440 - distance) / 150)) if enabled else 0.0
        proximity = proximity * proximity * (3 - 2 * proximity)
        target_x = max(-1, min(1, dx / (170 * scale))) if proximity else 0.0
        target_y = max(-1, min(1, -dy / (170 * scale))) if proximity else 0.0
        blend = 1 - math.exp(-max(0, seconds) * 10)
        self.x += (target_x - self.x) * blend
        self.y += (target_y - self.y) * blend
        self.weight += (proximity - self.weight) * blend
        return self.x, self.y, self.weight


def apply_pointer(parameters, activity, pointer):
    result = dict(parameters)
    if not pointer or activity in ('sleep', 'phone', 'lift', 'land', 'head_rub', 'mouse_wave'):
        return result
    x, y, weight = pointer
    weight = max(0, min(1, weight))
    result['ParamEyeBallX'] = max(-1, min(1,
        result.get('ParamEyeBallX', 0) * (1-weight) + .65*x*weight))
    result['ParamEyeBallY'] = max(-1, min(1,
        result.get('ParamEyeBallY', 0) * (1-weight) + .45*y*weight))
    # Singing/feeding own the head-to-microphone/hand relationship.
    if activity not in ('sing', 'turn', 'eat'):
        result['ParamAngleX'] = max(-30, min(30, result.get('ParamAngleX', 0) + 18*x*weight))
        result['ParamAngleY'] = max(-30, min(30, result.get('ParamAngleY', 0) + 8*y*weight))
        result['ParamBodyAngleX'] = max(-10, min(10, result.get('ParamBodyAngleX', 0) + 4.5*x*weight))
    return result
