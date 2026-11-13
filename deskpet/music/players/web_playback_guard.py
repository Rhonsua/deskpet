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
    """Confirm a requested start without rewinding already-heard audio."""
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
        self.target, self.seek_started = 0, now
        self.has_played = False
        self.observed_at = None
        self.sample_clock, self.sample_media, self.sample_rate = None, None, 1

    def cancel(self):
        self.active = False

    def update(self, value, now):
        if not self.active:
            return None
        duration, position = value.get('duration', 0), value.get('position', 0)
        rate = max(.1, min(16, value.get('playback_rate', 1)))
        if (value.get('has_video') and duration > 0 and not value.get('error') and
                abs(position - self.target) < 1 and self.observed_at is None):
            self.observed_at = now
        if (not value.get('has_video') or duration <= 0 or value.get('error') or
                value.get('seeking') or value.get('ready_state', 0) < 2):
            self.deadline = now + 2
            return None
        if self.origin is not None:
            if now >= self.settled_at:
                self.active = False
                return None
            previous_position, previous_time = self.origin
            elapsed = now - previous_time
            # Browser snapshots and their IPC delivery can be unevenly delayed.
            # Compare capture times too, rather than treating catch-up as a seek.
            clock = value.get('sample_clock')
            media = (value.get('token'), value.get('media_id'))
            if (isinstance(clock, (int, float)) and self.sample_clock is not None and
                    media == self.sample_media and clock >= self.sample_clock):
                elapsed = max(elapsed, clock - self.sample_clock)
            expected = previous_position + elapsed * max(rate, self.sample_rate)
            # Bilibili can restore history AFTER a successful seek to zero.
            # Return to the continuous timeline, never replay the heard intro.
            if position > expected + max(2.5, rate * 2):
                self.target = min(expected, max(0, duration - .2))
                self.seek_started = now
                self.observed_at = None
                self.origin, self.deadline = None, now
            else:
                self.origin = (position, now)
                self.sample_clock, self.sample_media, self.sample_rate = clock, media, rate
                if now >= self.settled_at or value.get('ended'):
                    self.active = False
                return None
        # A slow WebView report can arrive after the first two seconds have
        # already played. The page acknowledges seek completion independently
        # of readyState/playing; don't mistake reporting lag for a failed seek.
        elapsed = None
        if value.get('restart_observed'):
            elapsed = max(0, value.get('restart_elapsed', 0))
        elif self.observed_at is not None:
            elapsed = now - self.observed_at
        elif value.get('restart_settled'):
            elapsed = now - self.seek_started
        window = max(2, elapsed * rate + 1.25) if elapsed is not None else min(2, duration / 2)
        near_target = max(0, self.target - .5) <= position < self.target + window
        if (value.get('playing') and not value.get('ended') and not value.get('seeking') and
                duration > 0 and near_target):
            self.origin = (position, now)
            self.sample_clock = value.get('sample_clock')
            self.sample_media = (value.get('token'), value.get('media_id'))
            self.sample_rate = rate
            if not self.has_played:
                self.settled_at = now + self.settle_for
            self.has_played = True
            self.active = self.settle_for > 0
            return None
        # Buffering and an in-flight seek need time, not another seek to zero.
        # If we already landed at the target but autoplay is blocked, leave the
        # page there for the user instead of refreshing it repeatedly.
        if abs(position - self.target) < 1 and not value.get('ended'):
            self.deadline = now + 2
            return None
        if now < self.deadline:
            return None
        self.deadline = now + 2
        self.seek_started = now
        self.observed_at = None
        self.attempts += 1
        if self.attempts <= 3:
            return 'restore' if self.has_played else 'restart'
        self.active = False
        return 'reload' if self.allow_reload and not self.has_played else 'failed'
