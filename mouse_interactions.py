"""Unpressed mouse gestures with explicit exclusions, dwell and cooldowns."""
import math
from collections import deque

REACTION_SECONDS = {'head_rub': 2.2, 'mouse_wave': 2.4}


class ActiveHeadPetting:
    """Explicit glove contact, sampled in seconds rather than pixels per frame.

    Visual response is continuous. The returned bool is an eligible stroke, not
    a grant: the caller separately enforces the minute/day growth limits.
    """
    def __init__(self):
        self.strength = self.direction = 0.0
        self.phase = 'idle'
        self.previous = None
        self.age = self.still = self.clock = self.reward_distance = 0.0
        self.path = deque()

    def leave(self):
        self.previous = None
        self.age = self.still = self.reward_distance = 0.0
        self.path.clear()

    def step(self, x, y, seconds, *, contact=False, head_width=115, scale=1):
        dt = max(0, min(.2, seconds))
        self.clock += dt
        target = direction = 0.0
        eligible = False
        if contact:
            dx, dy = ((0, 0) if self.previous is None else
                      (x-self.previous[0], y-self.previous[1]))
            distance = math.hypot(dx, dy)
            # A teleport or a very fast pass must not become a credited stroke.
            if distance > max(30*scale, 700*scale*dt):
                self.leave()
                contact = False
            else:
                self.previous = (x, y)
                self.age += dt
                self.still = 0.0 if distance > .05*scale else self.still + dt
                self.path.append((self.clock, distance))
                while self.path and self.path[0][0] < self.clock-1.0:
                    self.path.popleft()
                travel = sum(item[1] for item in self.path)
                threshold = max(10*scale, head_width*.16)
                moving = self.age >= .12 and travel >= threshold and self.still < .25
                self.phase = 'stroking' if moving else 'contact'
                # A stationary hand gets a greeting then relaxes, with no reward.
                target = (.65 + .25*min(1, travel/(head_width*.6)) if moving else
                          .4*max(0, 1-max(0, self.still-.65)/.8))
                if distance:
                    direction = max(-1, min(1, dx/max(dt, .001)/(80*scale)))
                if moving:
                    self.reward_distance += distance
                    if self.reward_distance >= threshold:
                        self.reward_distance = 0.0
                        eligible = True
        if not contact:
            self.leave()
            self.phase = 'releasing' if self.strength > .01 else 'idle'
        self.strength += (target-self.strength)*(1-math.exp(-dt/(.075 if target > self.strength else .1)))
        self.direction += (direction-self.direction)*(1-math.exp(-dt/.12))
        if self.strength < .001:
            self.strength = 0.0
        return eligible


def apply_active_petting(parameters, activity, petting):
    """Drive Cubism's authored press, plus existing expression/hair parameters."""
    result = dict(parameters)
    strength, direction = petting or (0.0, 0.0)
    strength = max(0, min(1, strength))
    direction = max(-1, min(1, direction))
    if activity in ('sleep', 'phone', 'lift', 'land', 'eat', 'walk-left', 'walk-right'):
        strength = 0.0
    # Authored inspection motions may drive this parameter without active input.
    # Normal motion sampling resets it to zero; old models filter the unknown ID.
    result.setdefault('ParamHeadPat', 0.0)
    if not strength:
        return result
    result['ParamHeadPat'] = strength
    targets = {'ParamEyeLOpen': .03, 'ParamEyeROpen': .03,
               'ParamBrowLY': .3, 'ParamBrowRY': .3, 'ParamMouthOpenY': .03,
               'ParamEyeBallX': 0.0, 'ParamEyeBallY': 0.0,
               'ParamAngleZ': 5*direction, 'ParamHairSide': .28*direction,
               'ParamHairBack': -.22*direction}
    for key, target in targets.items():
        eye = key in ('ParamEyeLOpen', 'ParamEyeROpen')
        # Contact (.4) is soft half-lidded; a sustained stroke (>= .65)
        # reaches the model's closed-eye key instead of looking half asleep.
        weight = min(1, strength/.65) if eye else strength
        result[key] = result.get(key, 1.0 if eye else 0.0)*(1-weight) + target*weight
    return result


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
