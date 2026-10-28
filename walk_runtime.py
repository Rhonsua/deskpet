"""Qt integration shared by PNG sequences and optional Cubism walking motions."""
import time

from PySide6.QtCore import QPoint

from walk_controller import WalkController


class WalkRuntime:
    def init_walk(self):
        try:
            deadline = float(self.panel.settings.value('walk_cooldown_until', 0))
        except (ValueError, TypeError):
            deadline = 0
        self.walk_controller = WalkController(cooldown_until=deadline)
        self.walk_spec = None
        self.walk_canvas_height = 0
        self.walk_frames = {}
        self.walk_bounds = None
        self.auto_walk_enabled = self.panel.settings.value('random_walk', True, type=bool)

    def walk_supported(self):
        return self.walk_spec is not None

    def walk_busy_windows(self):
        windows = [self.panel, self.toolbar, self.bubble, getattr(self, 'chat_window', None)]
        for name in ('music_companion', 'mod_host'):
            owner = getattr(self, name, None)
            windows.append(getattr(owner, 'window', None))
        return any(window is not None and window.isVisible() for window in windows)

    def walk_eligible(self, *, starting=True, manual=False):
        if not self.walk_supported() or not self.isVisible():
            return False
        if (self.dragging or self.petting or self.dock_edge or self.press_point is not None
                or self.behavior.mode not in ('idle', 'listen') or self.playing
                or self.active_petting.strength > .01):
            return False
        if starting:
            if self.behavior.layers or self.click_timer.isActive() or self.hold_timer.isActive():
                return False
            if not manual and (self.walk_busy_windows() or time.monotonic() - self.last_interaction < 15):
                return False
        elif self.behavior.activity not in ('walk-left', 'walk-right') or self.walk_busy_windows():
            return False
        return True

    def set_auto_walk(self, enabled):
        self.auto_walk_enabled = bool(enabled)
        self.panel.settings.setValue('random_walk', self.auto_walk_enabled)
        self.panel.settings.sync()
        if not enabled:
            self.stop_walk()
        self.refresh_walk_controls()

    def refresh_walk_controls(self):
        available = self.walk_supported()
        for name in ('walk_button', 'walk_toggle'):
            control = getattr(self.panel, name, None)
            if control is not None:
                control.setEnabled(available)
                control.setToolTip('左右序列帧 / Live2D 散步动作' if available else '当前角色没有配置散步动作')
        toggle = getattr(self.panel, 'walk_toggle', None)
        if toggle is not None:
            toggle.blockSignals(True)
            toggle.setChecked(self.auto_walk_enabled)
            toggle.blockSignals(False)
        if self.toolbar.mode == 'rest' and self.toolbar.isVisible():
            self.toolbar.page('rest')

    def toggle_walk(self, checked=False):
        if self.walk_controller.active:
            self.stop_walk()
            return
        if not self.start_walk():
            self.bubble.say('当前角色还没有散步动作。' if not self.walk_supported()
                            else '先回到空闲状态，离开桌面边缘再散步吧。')

    def start_walk(self, *, automatic=False, direction=None, cycles=None):
        if not self.walk_eligible(manual=not automatic):
            return False
        # Manual starts dismiss their own controls; other open tools still block.
        if not automatic:
            self.panel.hide()
            self.toolbar.hide()
            self.bubble.hide()
            if self.walk_busy_windows():
                return False
        bounds = self.screen_bounds()
        left, right = bounds.left(), bounds.right() + 1 - self.width()
        if self.y() < bounds.top() or self.y() + self.height() > bounds.bottom() + 1:
            return False
        spec = self.walk_spec
        if self.live2d_renderer is not None:
            factor = .5 * self.scale
        else:
            frame = self.scaled_frames.get('walk-left:0')
            if frame is None or not self.walk_canvas_height:
                return False
            factor = frame.height() / self.walk_canvas_height
        if not self.walk_controller.start(self.x(), left, right, stride=spec.stride,
                                          cycle_seconds=spec.cycle_seconds, scale=factor,
                                          automatic=automatic, direction=direction, cycles=cycles):
            return False
        name = 'left' if self.walk_controller.direction < 0 else 'right'
        if not self.behavior.begin_walk(name):
            self.walk_controller.cancel()
            return False
        self.walk_bounds = bounds
        if automatic:
            self.panel.settings.setValue('walk_cooldown_until', self.walk_controller.cooldown_until)
            self.panel.settings.sync()
        self.update()
        return True

    def stop_walk(self):
        controller = getattr(self, 'walk_controller', None)
        if controller is None:
            return
        was_active = controller.active
        controller.cancel()
        self.behavior.end_walk()
        self.walk_bounds = None
        if was_active:
            self.last_interaction = time.monotonic()
            self.save_position()
            self.update()

    def tick_walk(self, delta):
        controller = self.walk_controller
        if controller.active:
            bounds = self.screen_bounds()
            changed_bounds = bounds != self.walk_bounds
            if not self.walk_eligible(starting=False) or changed_bounds:
                self.stop_walk()
                # A changed monitor/work area may no longer contain the pet.
                if changed_bounds:
                    from edge_docking import clamp_position
                    self.move(clamp_position(self.pos(), self.size(), bounds))
                return
            x = controller.step(delta, left=bounds.left(), right=bounds.right() + 1 - self.width())
            if x is not None:
                self.move(QPoint(round(x), self.y()))
            if not controller.active:
                self.behavior.end_walk()
                self.walk_bounds = None
                self.last_interaction = time.monotonic()
                self.save_position()
        elif controller.automatic_due(eligible=self.auto_walk_enabled and self.walk_eligible()):
            self.start_walk(automatic=True)
