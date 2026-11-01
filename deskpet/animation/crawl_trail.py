"""Leave a world-space ribbon along actual travel, then fade each completed cycle."""
from dataclasses import dataclass

from PySide6.QtCore import QRect

from deskpet.animation.crawl_movement import CYCLE_DURATION, distance


@dataclass
class RibbonPatch:
    rect: QRect
    born: float
    fade_at: float | None = None
    fade_after_cycle: int | None = None

    def visible_rect(self, now):
        # Time affects only opacity. Geometry is produced by actual movement.
        return QRect(self.rect)


class CrawlTrail:
    lifetime = 5.0
    hold_cycles = 3
    # Three retained cycles plus the older ribbons still fading for five seconds.
    capacity = 6

    def __init__(self):
        self.frames = []
        self.previous = None
        self.previous_elapsed = 0.0
        self.active = None
        self.completed_cycles = 0

    def clear(self):
        self.frames.clear()
        self.previous = None
        self.active = None
        self.completed_cycles = 0

    def prune(self, now):
        self.frames = [f for f in self.frames
                       if f.fade_at is None or now-f.fade_at < self.lifetime]

    def _finish(self, now):
        self.completed_cycles += 1
        if self.active is not None:
            self.active.fade_after_cycle = self.completed_cycles + self.hold_cycles - 1
            self.active = None
        for frame in self.frames:
            if (frame.fade_at is None and frame.fade_after_cycle is not None
                    and frame.fade_after_cycle <= self.completed_cycles):
                frame.fade_at = max(frame.born, now)

    def stop(self, now):
        # With no further cycles coming, let retained ribbons fade naturally.
        for frame in self.frames:
            if frame.fade_at is None:
                frame.fade_at = max(frame.born, now)
        self.active = None
        self.completed_cycles = 0
        self.previous = None

    def _extend(self, old, rect, now):
        # The emitter sits behind the head, matching the reference ribbon.
        # Only the segment it actually swept is added. The old tail stays put.
        start = old.x() + round(old.width()*.47)
        end = rect.x() + round(rect.width()*.47)
        if start == end:
            return
        swept = QRect(min(start, end), round(old.y()+old.height()*.27),
                      abs(end-start), round(old.height()*.68))
        if self.active is None:
            self.active = RibbonPatch(swept, now)
            self.frames.append(self.active)
            self.frames = self.frames[-self.capacity:]
        else:
            self.active.rect = self.active.rect.united(swept)

    def capture(self, rect, now, elapsed):
        self.prune(now)
        elapsed = max(0., elapsed)
        if elapsed < self.previous_elapsed:
            self.stop(now)
        old = self.previous
        if old is not None:
            dx, dy = rect.x()-old.x(), rect.y()-old.y()
            if abs(dx)+abs(dy) > 28:
                self.clear()
                return
            first_cycle = int(self.previous_elapsed / CYCLE_DURATION)
            cycle = int(elapsed / CYCLE_DURATION)
            segment_start = old
            for index in range(first_cycle, cycle):
                boundary = (index+1)*CYCLE_DURATION
                # A frame may straddle the loop boundary. Attribute the final
                # few pixels to the finishing action, not the next one.
                total = distance(elapsed)-distance(self.previous_elapsed)
                ratio = ((distance(boundary)-distance(self.previous_elapsed))/total
                         if total > 0 else 0.)
                ratio = max(0., min(1., ratio))
                boundary_rect = old.translated(round(dx*ratio), round(dy*ratio))
                self._extend(segment_start, boundary_rect, now)
                self._finish(now-(elapsed-boundary))
                segment_start = boundary_rect
            self._extend(segment_start, rect, now)
        self.previous = QRect(rect)
        self.previous_elapsed = elapsed

    def opacity(self, frame, now):
        if frame.fade_at is None:
            return .78
        remaining = max(0., min(1., 1-(now-frame.fade_at)/self.lifetime))
        return .78 * remaining**1.5
