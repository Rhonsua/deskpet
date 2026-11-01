"""Continuous, planted-foot phrases over the existing independent leg rig."""
import math

PHRASE_SECONDS = 4.8
CYCLE_SECONDS = PHRASE_SECONDS * 4
PHRASES = ('alternating_taps', 'slow_weight_shift', 'double_taps', 'step_and_rest')


def _smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def _pulse(t, start, end, hold=False):
    if t <= start or t >= end:
        return 0.0
    u = (t-start)/(end-start)
    if hold:
        return _smooth(u/.3) * _smooth((1-u)/.3)
    return .5 - .5 * math.cos(math.tau*u)


def footwork(seconds):
    t = max(0, seconds) % CYCLE_SECONDS
    phrase = min(3, int(t / PHRASE_SECONDS))
    local = t - phrase*PHRASE_SECONDS
    events = []
    if phrase == 0:
        for i in range(8):
            events.append((i*.6, (i+1)*.6, i % 2, 20 if i < 4 else 24, False))
    elif phrase == 1:
        for i in range(4):
            events.append((i*1.2, (i+1)*1.2, i % 2, 28, True))
    elif phrase == 2:
        for i in range(4):
            events.extend(((i*1.2, i*1.2+.44, i % 2, 18, False),
                           (i*1.2+.56, i*1.2+1.1, i % 2, 27, False)))
    else:
        for i, side, amplitude in ((0, 0, 16), (1, 1, 16), (2, 0, 27),
                                    (3, 1, 27), (5, 1, 23), (6, 0, 20)):
            events.append((i*.6, (i+1)*.6, side, amplitude, False))
    legs, weight = [0.0, 0.0], 0.0
    for start, end, side, amplitude, hold in events:
        pulse = _pulse(local, start, end, hold)
        legs[side] += amplitude * pulse
        # Character-left is screen-right: lean towards the opposite planted foot.
        weight += (-1 if side == 0 else 1) * pulse
    return {'left': legs[0], 'right': legs[1], 'weight': weight,
            'phrase': PHRASES[phrase]}


def apply_footwork(parameters, seconds):
    result = dict(parameters)
    step = footwork(seconds)
    # The support foot stays at neutral. Negative values of the old sine loop
    # extended/slid it while the opposite foot was lifting.
    result['ParamLegLSwing'] = step['left']
    result['ParamLegRSwing'] = step['right']
    # Rotation8's old yaw binding adds 0.2 degrees of side tilt per BodyX unit.
    # Cancel it through its 0.3-degree BodyZ binding so yaw does not dictate which
    # foot bears weight. The shared torso perspective itself remains unchanged.
    result['ParamBodyAngleZ'] = max(-10, min(10,
        result.get('ParamBodyAngleZ', 0)*.25 + 4*step['weight']
        - result.get('ParamBodyAngleX', 0)*2/3))
    return result
