"""Qt bridge for optional local mods and shared reminder delivery."""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from .manager import ModManager
from .loader import discover


class ModHost(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.window = None
        self.manager = ModManager(pet.panel.data_dir / 'mods', self.deliver)
        self.packages_dir = pet.panel.data_dir / 'mod-packages'
        try:
            self.packages_dir.mkdir(parents=True, exist_ok=True)
            packages, errors = discover(self.packages_dir)
        except OSError:
            packages, errors = [], ['Mod 文件夹无法创建，请检查目录权限。']
        for manifest, factory in packages:
            try:
                self.manager.register(manifest, factory)
            except ValueError:
                errors.append(f'{manifest.name}：扩展标识冲突，未加载。')
        self.discovery_warning = '\n'.join(errors)
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        # Also release stores when a test or another host destroys this pet.
        pet.destroyed.connect(lambda *_: self.manager.shutdown())

    def deliver(self, text):
        pet = self.pet
        if (not pet.isVisible() or pet.dragging or pet.dock_edge
                or pet.behavior.mode in ('sleep', 'phone') or pet.behavior.layers
                or pet.bubble.isVisible() or QApplication.activeModalWidget() is not None):
            return False
        music = getattr(pet, 'music_companion', None)
        for window in (pet.toolbar, pet.panel, getattr(pet, 'chat_window', None), self.window,
                       music.window if music else None):
            if window is not None and window.isVisible():
                return False
        # Reminders never trigger actions, rewards, or a state change.
        pet.bubble.say(text, 10_000)
        if self.manager.get_policy().get('sound_enabled', True):
            QApplication.beep()
        return True

    def tick(self):
        self.manager.tick()
        if self.window is not None:
            self.window.sync_state()

    def open(self):
        if self.window is None:
            from .window import ModsWindow
            self.window = ModsWindow(self.pet, self.manager)
        self.window.show_mods()

    def shutdown(self):
        self.timer.stop()
        self.manager.shutdown()
