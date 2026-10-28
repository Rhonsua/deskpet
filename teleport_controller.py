"""Passive vertical teleport timing, independent of Qt and character assets."""
import math
import random
import time
from dataclasses import dataclass


DURATION = 2.05
MOVE_AT = .80  # Both the character and the departure cloud are invisible.
COOLDOWN = 600.0


def ramp(value, start, end):
    t = max(0.0, min(1.0, (value - start) / (end - start)))
    return t * t * (3 - 2 * t)


@dataclass(frozen=True)
class TeleportVisual:
    person: float = 1.0
    smoke: float = 0.0
    bloom: float = 0.0
    burst: float = 0.0


def visual_at(seconds):
    """Cover -> vanish -> empty relocation -> smoke -> reveal."""
    if seconds < .74:
        return TeleportVisual(1 - ramp(seconds, .30, .43),
                              ramp(seconds, 0, .29) * (1 - ramp(seconds, .48, .74)),
                              ramp(seconds, 0, .28), seconds / .74)
    if seconds < .90:
        return TeleportVisual(0, 0, 0, 0)
    t = seconds - .90
    return TeleportVisual(ramp(t, .42, .96),
                          ramp(t, 0, .28) * (1 - ramp(t, .40, 1.15)),
                          ramp(t, 0, .28), t / 1.15)


class TeleportController:
    def __init__(self, cooldown_until=0, *, monotonic=time.monotonic,
                 wall_time=time.time, rng=None):
        self._now, self._wall = monotonic, wall_time
        self._rng = rng if rng is not None else random.Random()
        deadline = float(cooldown_until)
        self.cooldown_until = deadline if math.isfinite(deadline) else 0.0
        self._cooldown_at = monotonic() + max(0, self.cooldown_until - wall_time())
        self._check_at = max(self._cooldown_at, monotonic() + self._rng.uniform(45, 120))
        self.active = False
        self.elapsed = 0.0
        self.moved = False
        self.destination = 0

    @property
    def visual(self):
        return visual_at(self.elapsed) if self.active else TeleportVisual()

    def automatic_due(self, eligible):
        now = self._now()
        if now < self._check_at or now < self._cooldown_at:
            return False
        self._check_at = now + self._rng.uniform(45, 120)
        return bool(eligible and not self.active)

    def start(self, y, top, bottom, *, height):
        """Only the passive scheduler calls this; bounds already subtract height."""
        if self.active or self._now() < self._cooldown_at:
            return False
        if not all(math.isfinite(v) for v in (y, top, bottom, height)):
            return False
        if height <= 0 or not top <= y <= bottom:
            return False
        minimum = max(48, height * .40)
        rooms = {-1: y - top, 1: bottom - y}
        choices = [side for side, room in rooms.items() if room >= minimum]
        if not choices:
            return False
        side = self._rng.choice(choices)
        distance = self._rng.uniform(minimum, min(rooms[side], height * 2))
        self.destination = max(top, min(bottom, round(y + side * distance)))
        self.elapsed = 0.0
        self.moved = False
        self.active = True
        delay = COOLDOWN + self._rng.uniform(0, 180)
        self._cooldown_at = self._now() + delay
        self._check_at = self._cooldown_at
        self.cooldown_until = self._wall() + delay
        return True

    def step(self, seconds):
        if not self.active:
            return None
        self.elapsed += min(.1, max(0, seconds)) if math.isfinite(seconds) else 0
        destination = None
        if not self.moved and self.elapsed >= MOVE_AT:
            self.moved = True
            destination = self.destination
        if self.elapsed >= DURATION:
            self.active = False
        return destination

    def cancel(self):
        self.active = False
