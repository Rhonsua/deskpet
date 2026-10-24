"""Time-based, model-independent lifted-pet reaction values.

The dedicated arm parameters are normalized to the Cubism model's 0..1 range.
The sampled values can also be baked into a Viewer inspection motion.
"""

import math


LIFT_ARM_IDS = ('ParamLiftArmL', 'ParamLiftArmR')
LIFT_FEAR_ID = 'ParamLiftFear'
LEGACY_ARM_IDS = ('ParamArmLSwing', 'ParamArmRSwing')
LIFT_START_SECONDS = 0.15
LIFT_RELEASE_SECONDS = 0.25
FLAPS_PER_SECOND = 2.25
FLAPS_PER_BURST = 3
PAUSE_SECONDS = 0.25


def _smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def _arm_wave(seconds, phase_offset=0.0):
    burst = FLAPS_PER_BURST / FLAPS_PER_SECOND
    within = seconds % (burst + PAUSE_SECONDS)
    if within >= burst:
        return 0.5
    # A small offset keeps the hands alive without turning the pose into a wave.
    edge_taper = math.sin(math.pi * within / burst) ** 2
    return 0.5 + 0.42 * math.sin(math.tau * FLAPS_PER_SECOND * within + phase_offset * edge_taper)


def sample_lift_reaction(seconds):
    """Return the lift pose at an absolute elapsed time, regardless of frame rate.

    The first 0.15 seconds ease in from the neutral face and lowered arms. Three
    flaps are followed by a short hold, and the pattern repeats for any duration.
    """
    elapsed = max(0.0, seconds)
    enter = _smoothstep(elapsed / LIFT_START_SECONDS)
    wave_time = max(0.0, elapsed - LIFT_START_SECONDS)
    return {
        'ParamLiftArmL': enter * _arm_wave(wave_time),
        'ParamLiftArmR': enter * _arm_wave(wave_time, -math.tau * FLAPS_PER_SECOND * 0.045),
        'ParamLiftFear': enter,
        'ParamEyeLOpen': 1.0 - enter,
        'ParamEyeROpen': 1.0 - enter,
        'ParamBrowLY': -0.55 * enter,
        'ParamBrowRY': -0.55 * enter,
        # The Cubism fear deformer narrows this opening into a small startled O.
        'ParamMouthOpenY': 0.6 * enter,
        'ParamArmLSwing': 0.0,
        'ParamArmRSwing': 0.0,
    }


class LiftReactionOverlay:
    """Compose the lift face and arms over the final sampled render parameters."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Forget any lift or release transition, such as when a window hides."""
        self.last_activity = None
        self.last_lift_seconds = None
        self.entry_start_seconds = 0.0
        self.entry_sample = {}
        self.last_values = {}
        self.entry_values = {}
        self.release_values = {}

    def apply(self, activity, seconds, parameters, parameter_ids,
              enabled=True, resume_activity=None):
        if not enabled:
            self.reset()
            return parameters
        # Old models must preserve their original motion and expression exactly.
        if not set(LIFT_ARM_IDS).issubset(parameter_ids):
            self.last_activity = activity
            self.last_lift_seconds = None
            self.entry_sample = {}
            self.last_values = dict(parameters)
            self.entry_values = {}
            self.release_values = {}
            return parameters

        output = dict(parameters)
        supported = set(parameter_ids)
        if activity == 'lift':
            new_lift = (self.last_activity != 'lift' or self.last_lift_seconds is None
                        or seconds + 1e-9 < self.last_lift_seconds)
            if new_lift:
                # A lift returning from the edge still has its original activity
                # clock. Give that new entrance its own 0.15-second transition.
                reentering = (self.last_lift_seconds is not None
                              and seconds + 1e-9 >= self.last_lift_seconds
                              and self.last_activity != 'land')
                self.entry_start_seconds = seconds if reentering else 0.0
                self.entry_sample = sample_lift_reaction(self.entry_start_seconds)
                self.entry_values = {
                    key: self.last_values.get(key, parameters.get(key, value))
                    for key, value in self.entry_sample.items()
                    if key in supported and key not in LEGACY_ARM_IDS
                }
            sampled = sample_lift_reaction(seconds)
            startup_remaining = 1.0 - _smoothstep(
                (seconds - self.entry_start_seconds) / LIFT_START_SECONDS)
            for key, value in sampled.items():
                if key in supported and key not in LEGACY_ARM_IDS:
                    initial = self.entry_values.get(key, sampled.get(key, value))
                    if self.entry_start_seconds:
                        # The cycle may descend sharply during this fade. A
                        # convex blend keeps normalized arms inside 0..1.
                        output[key] = initial * startup_remaining + value * (1.0 - startup_remaining)
                    else:
                        # The pure sample already contains the original onset;
                        # only correct it for a non-neutral preceding pose.
                        output[key] = value + (initial - self.entry_sample[key]) * startup_remaining
            # The legacy parameters add a competing shoulder movement.
            for key in LEGACY_ARM_IDS:
                if key in supported:
                    output[key] = 0.0
            self.release_values = {}
            self.last_lift_seconds = seconds
        elif activity == 'land':
            if self.last_activity == 'lift':
                self.release_values = {
                    key: self.last_values[key] for key in sample_lift_reaction(0)
                    if key in supported and key in self.last_values
                    and key not in LEGACY_ARM_IDS
                }
            remaining = 1.0 - _smoothstep(seconds / LIFT_RELEASE_SECONDS)
            for key in LIFT_ARM_IDS + (LIFT_FEAR_ID,):
                if key in supported:
                    output[key] = self.release_values.get(key, 0.0) * remaining
            for key, start in self.release_values.items():
                if key not in LIFT_ARM_IDS + (LIFT_FEAR_ID,) and remaining > 0:
                    target = (0.0 if resume_activity == 'sleep' and key.endswith('Open')
                              else parameters.get(key, 1.0 if key.endswith('Open') else 0.0))
                    output[key] = target + (start - target) * remaining
            if resume_activity == 'sleep':
                for key in ('ParamEyeLOpen', 'ParamEyeROpen'):
                    if key in supported:
                        output[key] = 0.0
            self.last_lift_seconds = None
        else:
            # Docking and interrupted actions can exit lift without a landing.
            for key in LIFT_ARM_IDS + (LIFT_FEAR_ID,):
                if key in supported:
                    output[key] = 0.0
            self.release_values = {}
            # Retain the last lift clock through edge-dock's temporary idle
            # frames so a pull-back can be distinguished from a fresh drag.

        self.last_activity = activity
        self.last_values = dict(output)
        return output
