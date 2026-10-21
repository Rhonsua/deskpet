"""Bounded pickup/drop elasticity and pointer-driven hanging sway."""
import math


class DragSway:
    def __init__(self):
        self.angle = self.velocity = self.target = 0.0

    def start(self):
        self.angle = self.velocity = self.target = 0.0

    def move(self, dx, seconds, scale=1):
        self.target = max(-9, min(9, -dx / max(.016, seconds) * .012 / scale))

    def release(self):
        self.target = 0.0

    def step(self, seconds):
        seconds = max(0, min(.1, seconds))
        steps = max(1, math.ceil(seconds * 120))
        dt = seconds / steps
        for _ in range(steps):
            self.velocity += (52 * (self.target - self.angle) - 10 * self.velocity) * dt
            self.angle += self.velocity * dt
            self.target *= math.exp(-8 * dt)


def interaction_pose(activity, seconds, sway=0):
    """Scale about the held point; settle about the feet after release."""
    t = max(0, seconds)
    if activity == 'lift':
        sy = 1 + .045 * (1 - math.exp(-10*t)) + .14 * math.exp(-5*t) * math.sin(15*t)
        angle = sway + 2.5 * math.exp(-3*t) * math.sin(14*t)
    elif activity == 'land':
        sy = 1 - .14 * math.exp(-7*t) * math.sin(17*t)
        angle = sway * math.exp(-7*t)
    else:
        return 0.0, 1.0, 1.0
    return angle, sy ** -.5, sy
