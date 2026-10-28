"""Interruptible passive teleport shared by static and Live2D characters."""
import time
from PySide6.QtCore import QRectF
from PySide6.QtGui import QRegion
from teleport_controller import TeleportController


class TeleportRuntime:
    def init_teleport(self):
        try:
            deadline = float(self.panel.settings.value('teleport_cooldown_until', 0))
        except (TypeError, ValueError):
            deadline = 0
        self.teleport_controller = TeleportController(deadline)
        self.teleport_bounds = None
        self.teleport_body = QRectF()
        self.auto_teleport_enabled = self.panel.settings.value('random_teleport', True, type=bool)

    def set_auto_teleport(self, enabled):
        self.auto_teleport_enabled = bool(enabled)
        self.panel.settings.setValue('random_teleport', self.auto_teleport_enabled)
        self.panel.settings.sync()
        if not enabled:
            self.stop_teleport()

    def teleport_eligible(self, *, starting=True):
        if (not self.auto_teleport_enabled or not self.isVisible()
                or self.dragging or self.petting or self.dock_edge or self.press_point is not None
                or self.behavior.mode not in ('idle', 'listen') or self.playing
                or self.active_petting.strength > .01 or self.walk_controller.active
                or self.walk_busy_windows() or self.click_timer.isActive() or self.hold_timer.isActive()):
            return False
        if starting:
            return not self.behavior.layers and time.monotonic() - self.last_interaction >= 15
        return self.behavior.action == 'teleport'

    def _start_teleport(self):
        if not self.teleport_eligible():
            return False
        bounds = self.screen_bounds()
        if self.x() < bounds.left() or self.x() + self.width() > bounds.right() + 1:
            return False
        if not self.teleport_controller.start(self.y(), bounds.top(),
                                              bounds.bottom() + 1 - self.height(), height=self.height()):
            return False
        if not self.behavior.begin_teleport():
            self.teleport_controller.cancel()
            return False
        self.teleport_bounds = bounds
        self.teleport_body = QRectF(self.hit_region.boundingRect())
        if self.teleport_body.isEmpty():
            self.teleport_body = QRectF(self.rect()).adjusted(24, 12, -24, -20)
        self.panel.settings.setValue('teleport_cooldown_until', self.teleport_controller.cooldown_until)
        self.panel.settings.sync()
        self.effects.sync()
        self.update()
        return True

    def stop_teleport(self):
        controller = getattr(self, 'teleport_controller', None)
        if controller is None:
            return
        was_active = controller.active or self.behavior.has_action('teleport')
        controller.cancel()
        self.behavior.end_teleport()
        self.teleport_bounds = None
        if was_active:
            self.last_interaction = time.monotonic()
            self.save_position()
            self.update()
            self.effects.sync()

    def stop_roaming(self):
        self.stop_teleport()
        self.stop_walk()

    def tick_teleport(self, delta):
        controller = self.teleport_controller
        if controller.active:
            bounds = self.screen_bounds()
            changed_bounds = bounds != self.teleport_bounds
            if not self.teleport_eligible(starting=False) or changed_bounds:
                self.stop_teleport()
                if changed_bounds:
                    from edge_docking import clamp_position
                    self.move(clamp_position(self.pos(), self.size(), bounds))
                    self.save_position()
                return
            destination = controller.step(delta)
            if destination is not None:
                self.move(self.x(), destination)
            if not controller.active:
                self.stop_teleport()
            self.effects.sync()
        elif controller.automatic_due(self.teleport_eligible()):
            self._start_teleport()

    def paint_teleport(self, painter):
        controller = self.teleport_controller
        if not controller.active:
            return
        painter.resetTransform()
        painter.setOpacity(1)
        # Invisible frames do not leave an invisible click target behind.
        if controller.visual.person < .01:
            self.hit_region = QRegion()
