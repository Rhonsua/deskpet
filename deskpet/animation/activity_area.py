"""Persistent desktop roaming bounds; mouse dragging keeps physical screen bounds."""
import time

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QApplication

from deskpet.animation.edge_docking import clamp_position

AREA_KEY = 'activity_area/rect'


def read_area(settings):
    value = settings.value(AREA_KEY)
    return QRect(value) if isinstance(value, QRect) and value.isValid() else None


def roaming_bounds(pet):
    screen = pet.screen_bounds()
    area = getattr(pet, 'activity_area', None)
    return screen.intersected(area) if area is not None else screen


def roaming_allowed(pet, bounds):
    if getattr(pet, 'activity_area_picker', None) is not None:
        return False
    # Include the full character window, including its animation margin.
    return bounds.contains(QRect(pet.x(), pet.y(), pet.width(), pet.height()))


class ActivityAreaRuntime:
    def init_activity_area(self):
        self.activity_area = read_area(self.panel.settings)
        self.activity_area_picker = None

    def activity_area_text(self):
        area = getattr(self, 'activity_area', None)
        if area is None:
            return '活动范围：当前屏幕的整个可用桌面'
        text = f'活动范围：{area.width()} × {area.height()}，左上角 ({area.x()}, {area.y()})'
        if not roaming_allowed(self, roaming_bounds(self)):
            text += '\n当前桌宠不在范围内，或范围容不下桌宠；自主移动已暂停。'
        return text

    def refresh_activity_area_controls(self):
        label = getattr(self.panel, 'activity_area_note', None)
        if label is not None:
            label.setText(self.activity_area_text())
        button = getattr(self.panel, 'clear_activity_area_button', None)
        if button is not None:
            button.setEnabled(self.activity_area is not None)
        action = getattr(self, 'clear_activity_area_action', None)
        if action is not None:
            action.setEnabled(self.activity_area is not None)

    def select_activity_area(self, checked=False):
        if self.activity_area_picker is not None:
            self.activity_area_picker.raise_windows()
            return
        if self.dragging or self.press_point is not None:
            return
        from deskpet.ui.activity_area_picker import ActivityAreaPicker
        self.stop_roaming()
        self.behavior.layers = [a for a in self.behavior.layers if a.name != 'crawl']
        if self.petting:
            self.end_petting()
        self.panel.hide()
        self.toolbar.hide()
        self.bubble.hide()
        # Reserve some room to move, not just enough to hold a static pose.
        minimum = QSize(self.width() + 40, self.height() + 40)
        picker = ActivityAreaPicker(self, minimum, self.activity_area)
        self.activity_area_picker = picker
        picker.finished.connect(self._activity_area_selected)
        picker.open()

    def _activity_area_selected(self, area):
        self.activity_area_picker = None
        self.last_interaction = time.monotonic()
        if isinstance(area, QRect) and self.apply_activity_area(area):
            self.bubble.say('就在这片地方活动啦。可以随时重新框选。')
        self.refresh_activity_area_controls()

    def apply_activity_area(self, area):
        # One real monitor only: never allow movement through gaps between screens.
        if (not isinstance(area, QRect) or area.width() < self.width() + 40
                or area.height() < self.height() + 40
                or not any(s.availableGeometry().contains(area) for s in QApplication.screens())):
            return False
        self.stop_roaming()
        self.activity_area = QRect(area)
        self.panel.settings.setValue(AREA_KEY, self.activity_area)
        self.panel.settings.sync()
        self.fold_timer.stop()
        self.dock_edge = self.drag_dock_edge = ''
        self.dock_reveal = self.dock_target = 1.0
        # Applying a new range is the one explicit relocation. Later manual
        # drags outside it simply suspend roaming until the pet is put back.
        self.move(clamp_position(self.pos(), self.size(), area))
        self.save_position()
        self.last_interaction = time.monotonic()
        self.refresh_activity_area_controls()
        self.update()
        return True

    def clear_activity_area(self, checked=False):
        picker = getattr(self, 'activity_area_picker', None)
        if picker is not None:
            picker.finish(None)
        self.stop_roaming()
        self.activity_area = None
        self.panel.settings.remove(AREA_KEY)
        self.panel.settings.sync()
        self.last_interaction = time.monotonic()
        self.refresh_activity_area_controls()
        self.bubble.say('可以在当前屏幕自由活动啦。')
