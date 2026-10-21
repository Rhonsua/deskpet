"""Persistent intent plus interruptible, timed presentation overlays."""
from dataclasses import dataclass


MODES = ('idle', 'sleep', 'phone', 'sing', 'listen')


@dataclass
class Action:
    name: str
    remaining: float | None
    elapsed: float = 0.0


class PetBehavior:
    def __init__(self, mode='idle'):
        self.mode = mode if mode in MODES else 'idle'
        self.playing = False
        self.layers = []
        self.mode_elapsed = 0.0

    @property
    def activity_elapsed(self):
        return self.elapsed if self.layers else self.mode_elapsed

    @property
    def dragging(self):
        return bool(self.layers and self.layers[-1].name == 'lift')

    @property
    def action(self):
        return self.layers[-1].name if self.layers else 'idle'

    @property
    def elapsed(self):
        return self.layers[-1].elapsed if self.layers else 0.0

    @property
    def activity(self):
        if self.layers:
            return self.action
        if self.mode == 'listen':
            return 'idle'
        return 'sing' if self.mode == 'idle' and self.playing else self.mode

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError('Unknown activity: ' + str(mode))
        if mode != self.mode:
            self.mode_elapsed = 0.0
        self.mode = mode
        # A new explicit choice wins after the current physical drag finishes.
        self.layers = self.layers[-1:] if self.dragging else []

    def react(self, name, seconds):
        action = Action(name, max(0, seconds))
        self.layers = [action, self.layers[-1]] if self.dragging else [action]

    def has_action(self, name):
        return any(action.name == name for action in self.layers)

    def begin_drag(self):
        if not self.dragging:
            if self.action == 'land':
                self.layers.pop()  # A new drop supersedes the interrupted landing.
            self.layers.append(Action('lift', None))

    def end_drag(self, landing=True):
        if not self.dragging:
            return
        self.layers.pop()
        if landing:
            self.layers.append(Action('land', 0.65))

    def tick(self, seconds):
        seconds = max(0, seconds)
        while self.layers and seconds > 0:
            action = self.layers[-1]
            if action.remaining is None:
                action.elapsed += seconds
                return
            step = min(seconds, action.remaining)
            action.elapsed += step
            action.remaining -= step
            seconds -= step
            if action.remaining <= 1e-9:
                self.layers.pop()
            else:
                return
        if not self.layers:
            self.mode_elapsed += seconds
