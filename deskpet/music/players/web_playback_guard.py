"""Conservative completion fallback and bounded replay recovery, using host time."""


class TailCompletion:
    def __init__(self):
        self.reset()

    def reset(self):
        self.sample = None
        self.since = None

    def update(self, value, now, requested_play):
        position, duration = value.get('position', 0), value.get('duration', 0)
        eligible = (requested_play and value.get('seen_playing') and
                    value.get('has_video') and not value.get('error') and
                    not value.get('seeking') and value.get('ready_state', 0) >= 3 and
                    value.get('buffered_to_end') and duration > 0 and
                    0 <= duration - position <= .15)
        if not eligible:
            self.reset()
            return False
        sample = (value.get('token'), value.get('media_id'), position, duration)
        if (self.sample is None or sample[:2] != self.sample[:2] or
                abs(position - self.sample[2]) > .02 or
                abs(duration - self.sample[3]) > .02):
            self.sample, self.since = sample, now
        return now - self.since >= 4


class ReplayRecovery:
    """Require playback near zero before accepting the next completion."""
    def __init__(self):
        self.active = False
        self.origin = None

    @property
    def blocking(self):
        return self.active and self.origin is None

    def start(self, now, allow_reload=True, settle_for=0):
        self.active, self.deadline, self.attempts = True, now + 2, 0
        self.allow_reload = allow_reload
        self.origin, self.settle_for = None, settle_for

    def cancel(self):
        self.active = False

    def update(self, value, now):
        if not self.active:
            return None
        duration, position = value.get('duration', 0), value.get('position', 0)
        if self.origin is not None:
            previous_position, previous_time = self.origin
            rate = max(.1, min(16, value.get('playback_rate', 1)))
            # Bilibili can restore history AFTER a successful seek to zero.
            # Keep checking for jumps during the opening of a selected track.
            if position > previous_position + (now - previous_time) * rate + 1.25:
                self.origin, self.deadline = None, now
            else:
                self.origin = (position, now)
                if now >= self.settled_at or value.get('ended'):
                    self.active = False
                return None
        if (value.get('playing') and not value.get('seeking') and
                duration > 0 and 0 <= position < min(2, duration / 2)):
            self.origin = (position, now)
            self.settled_at = now + self.settle_for
            self.active = self.settle_for > 0
            return None
        if now < self.deadline:
            return None
        self.deadline = now + 2
        self.attempts += 1
        if self.attempts <= 3:
            return 'restart'
        self.active = False
        return 'reload' if self.allow_reload else 'failed'
