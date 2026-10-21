"""Unpressed mouse gestures with explicit exclusions, dwell and cooldowns."""
import math

REACTION_SECONDS = {'head_rub': 2.2, 'mouse_wave': 2.4}


class MouseInteractions:
    def __init__(self):
        self.previous = None
        self.previous_head = False
        self.head_distance = 0.0
        self.direction = self.reversals = 0
        self.hand_dwell = 0.0
        self.hand_latched = False
        self.rub_cooldown = self.wave_cooldown = 0.0

    def step(self, x, y, seconds, *, in_head=False, near_hand=False,
             enabled=True, scale=1):
        dt = max(0, min(.1, seconds))
        self.rub_cooldown = max(0, self.rub_cooldown-dt)
        self.wave_cooldown = max(0, self.wave_cooldown-dt)
        if not near_hand:
            self.hand_latched = False
        if not enabled:
            self.previous = None
            self.previous_head = False
            self.head_distance = self.reversals = self.direction = self.hand_dwell = 0
            return None
        dx, dy = (0, 0) if self.previous is None else (x-self.previous[0], y-self.previous[1])
        self.previous = (x, y)
        distance = math.hypot(dx, dy)
        if in_head and self.previous_head and distance <= 120*scale:
            self.head_distance = self.head_distance*math.exp(-dt/1.1) + distance
            if abs(dx) >= 2.5*scale:
                direction = 1 if dx > 0 else -1
                if self.direction and direction != self.direction:
                    self.reversals += 1
                self.direction = direction
        else:
            self.head_distance = self.reversals = self.direction = 0
        self.previous_head = in_head
        if self.head_distance >= 85*scale and self.reversals >= 2 and not self.rub_cooldown:
            self.head_distance = self.reversals = self.direction = 0
            self.rub_cooldown = 7
            return 'head_rub'
        if near_hand and not self.hand_latched and distance/max(dt, .001) < 85*scale:
            self.hand_dwell += dt
        else:
            self.hand_dwell = 0.0
        if self.hand_dwell >= 1.15 and not self.wave_cooldown:
            self.hand_latched = True
            self.hand_dwell = 0
            self.wave_cooldown = 16
            return 'mouse_wave'
        return None


def apply_mouse_reaction(parameters, activity, seconds):
    result = dict(parameters)
    if activity == 'head_rub':
        t = max(0, min(2.2, seconds))
        # Smooth onset/release; never blend two painted limb alternatives.
        u = min(1, t/.25, (2.2-t)/.4)
        envelope = max(0, u)**2 * (3-2*max(0, u))
        result.update(ParamEyeLOpen=1-.97*envelope,
                      ParamEyeROpen=1-.97*envelope,
                      ParamAngleZ=9*math.sin(t*5)*envelope,
                      ParamAngleX=3*math.sin(t*3)*envelope,
                      ParamEyeBallX=0.0, ParamBrowLY=.35*envelope,
                      ParamMouthOpenY=.12*envelope,
                      ParamHairSide=.35*math.sin(t*6)*envelope,
                      ParamHairBack=-.3*math.sin(t*6-.3)*envelope)
    return result
