"""Renderer-independent, interruptible walks and conservative automatic scheduling.

Coordinates are Qt-style logical pixels but this module has no Qt dependency.
PNG sequences and Live2D motions sample ``elapsed`` from the distance actually
travelled, so slow frames cannot advance the feet without moving the pet.
"""
import math
import random
import time


AUTO_COOLDOWN_SECONDS = 600.0
MAX_STEP_SECONDS = 0.1
RAMP_SECONDS = 0.18
WALK_SPEED_MULTIPLIER = 2.6  # Previous 2.0x pace, increased by another 30%.
ROUTE_DISTANCE_MULTIPLIER = 3
AUTO_DISTANCE_RANGE = (0.5, 2.0)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class WalkController:
    def __init__(self, cooldown_until=0.0, *, monotonic=time.monotonic,
                 wall_time=time.time, rng=None):
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._rng = rng if rng is not None else random.Random()
        self.cooldown_until = float(cooldown_until) if _finite(cooldown_until) else 0.0
        remaining = max(0.0, self.cooldown_until - wall_time())
        now = monotonic()
        self._cooldown_at = now + remaining
        self._auto_check_at = now + max(remaining, self._rng.uniform(30.0, 90.0))
        self.active = False
        self.direction = 1
        self.x = 0.0
        self.elapsed = 0.0
        self.cycle_seconds = 1.2
        self.automatic = False

    @property
    def phase(self):
        return (self.elapsed / self.cycle_seconds) % 1.0

    @property
    def cooldown_remaining(self):
        return max(0.0, self._cooldown_at - self._monotonic())

    def automatic_due(self, eligible=True):
        """Offer at most one attempt per random interval, never per-frame draws.

        Busy/hidden pets discard missed opportunities. The caller may further
        reject a due attempt (for example if neither direction has enough room).
        Such rejection does not consume the ten-minute cooldown.
        """
        now = self._monotonic()
        if now < self._auto_check_at or now < self._cooldown_at:
            return False
        self._auto_check_at = now + self._rng.uniform(30.0, 90.0)
        return bool(eligible and not self.active)

    def start(self, x, left, right, *, stride, cycle_seconds, scale=1.0,
              automatic=False, eligible=True, direction=None, cycles=None):
        """Start a finite route, keeping the pet's current saved mode untouched.

        ``left``/``right`` bound the window's x coordinate (window width already
        subtracted by the caller). ``stride`` is source-art pixels per full gait
        cycle. Both directions must be supplied by the renderer; no mirroring is
        performed here. Explicit directions are -1 or +1, otherwise choose among
        directions with room for at least one cycle. Default routes travel three
        times the original 2-4 cycles. Automatic routes choose a whole-cycle
        distance within 0.5-2x that manual route, limited by available space.
        Explicit cycle counts remain exact.
        """
        if self.active or not eligible or (automatic and self.cooldown_remaining > 0):
            return False
        if not all(_finite(value) for value in (x, left, right, stride, cycle_seconds, scale)):
            return False
        if left > right or not left <= x <= right or min(stride, cycle_seconds, scale) <= 0:
            return False
        if direction is not None and (isinstance(direction, bool) or direction not in (-1, 1)):
            return False
        if cycles is not None and (not _finite(cycles) or cycles < 1 or cycles != int(cycles)):
            return False
        step = stride * scale
        gait_speed = step / cycle_seconds
        speed = gait_speed * WALK_SPEED_MULTIPLIER
        if not math.isfinite(step) or step <= 0 or not math.isfinite(speed):
            return False
        room = {-1: x - left, 1: right - x}
        choices = [side for side in (-1, 1) if room[side] + 1e-9 >= step]
        if direction is not None:
            choices = [direction] if direction in choices else []
        if not choices:
            return False
        side = self._rng.choice(choices)
        available = int((room[side] + 1e-9) / step)
        count = min(int(cycles) if cycles is not None else
                    self._rng.randint(2, 4) * ROUTE_DISTANCE_MULTIPLIER,
                    available)
        if automatic and cycles is None:
            # Use the same feasible route a manual start would have taken.
            # Whole cycles preserve the settled pose when the route finishes.
            count = self._rng.randint(max(1, math.ceil(count * AUTO_DISTANCE_RANGE[0])),
                                      min(available, math.floor(count * AUTO_DISTANCE_RANGE[1])))
        self.direction = side
        self.x = self._start_x = float(x)
        self._left, self._right = float(left), float(right)
        self._distance = count * step
        self._gait_speed = gait_speed
        self._speed = speed
        self.cycle_seconds = float(cycle_seconds)
        self._ramp = min(RAMP_SECONDS, cycle_seconds * 0.25) / WALK_SPEED_MULTIPLIER
        # Two linear speed ramps together take one extra ramp interval.
        self._duration = count * cycle_seconds / WALK_SPEED_MULTIPLIER + self._ramp
        self._clock = self.elapsed = 0.0
        self.automatic = bool(automatic)
        self.active = True
        if automatic:
            delay = AUTO_COOLDOWN_SECONDS + self._rng.uniform(0.0, 180.0)
            self._cooldown_at = self._monotonic() + delay
            self._auto_check_at = self._cooldown_at
            self.cooldown_until = self._wall_time() + delay
        return True

    def cancel(self):
        """Forget the route immediately, preserving cooldown and last pose."""
        self.active = False

    def step(self, seconds, left=None, right=None):
        """Return a new x, including the final point, or None if not walking.

        Refresh screen bounds on each call when needed. If a screen disappears
        or its usable width changes, stop inside the new bounds. Sleeping or
        long GUI stalls consume at most 100 ms of movement and animation.
        """
        if not self.active:
            return None
        if left is not None:
            if not _finite(left):
                self.cancel()
                return None
            self._left = float(left)
        if right is not None:
            if not _finite(right):
                self.cancel()
                return None
            self._right = float(right)
        if self._left > self._right:
            self.cancel()
            return None
        if not self._left <= self.x <= self._right:
            self.x = max(self._left, min(self._right, self.x))
            self.cancel()
            return self.x
        dt = min(MAX_STEP_SECONDS, max(0.0, seconds)) if _finite(seconds) else 0.0
        self._clock = min(self._duration, self._clock + dt)
        t, ramp, duration = self._clock, self._ramp, self._duration
        if t < ramp:
            distance = self._speed * t * t / (2.0 * ramp)
        elif t > duration - ramp:
            distance = self._distance - self._speed * (duration - t) ** 2 / (2.0 * ramp)
        else:
            distance = self._speed * (t - ramp / 2.0)
        if duration - t < 1e-9:
            distance = self._distance
        requested = self._start_x + self.direction * distance
        self.x = max(self._left, min(self._right, requested))
        # Keep sampling authored animation time per distance, so the feet speed
        # up with the window without stretching stride or invalidating contact.
        self.elapsed = abs(self.x - self._start_x) / self._gait_speed
        if self.x != requested or duration - t < 1e-9:
            self.cancel()
        return self.x
