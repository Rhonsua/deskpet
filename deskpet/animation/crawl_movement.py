"""Forward travel is synchronized with the stretch phase of the prone pose."""
import math

CYCLE_DURATION = 2.8


def distance(seconds, scale=1.0):
    cycles, phase = divmod(max(0.0, seconds), CYCLE_DURATION)
    t = max(0.0, min(1.0, (phase / CYCLE_DURATION - .38) / .62))
    progress = t * t * (3 - 2 * t)
    return 48.0 * scale * (math.floor(cycles) + progress)
