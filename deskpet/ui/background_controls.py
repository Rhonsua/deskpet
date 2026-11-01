"""Shared image controls with independently persisted crops for each page."""
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .background import BackgroundPlacement, save_background


class PageBackgrounds(QObject):
    image_changed = Signal()

    def __init__(self, surface, settings, image_path, key, position_button, *, style=None, notify=None):
        super().__init__(surface)
        self.surface = surface
        self.settings = settings
        self.path = Path(image_path)
        self.key = key
        self.position_button = position_button
        self.style = style
        self.notify = notify or (lambda text: None)
        self.page = 'main'
        self.label = '当前页面'
        self.editing = False
        self.reload()

    def records(self):
        value = self.settings.value(self.key + '_placements')
        return dict(value) if isinstance(value, dict) else {}

    def position(self, page):
        # Earlier chat versions had one crop for the whole window. Keep that
        # appearance until each page is edited, without sharing future changes.
        value = self.records().get(page, self.settings.value(self.key + '_placement'))
        return BackgroundPlacement.read(value)

    def activate(self, page, label):
        self.page, self.label = page, label
        self.position_button.setToolTip('只调整“' + label + '”的显示区域，其他页面保持各自设置')
        if not self.editing:
            self.surface.set_placement(self.position(page))

    def reload(self):
        self.surface.set_placement(self.position(self.page))
        self.surface.set_surface(self.path)
        enabled = not self.surface.surface_image.isNull()
        self.position_button.setEnabled(enabled)
        if self.style:
            self.style(enabled)

    def save_position(self, page, placement):
        records = self.records()
        records[page] = BackgroundPlacement.read(placement).as_dict()
        self.settings.setValue(self.key + '_placements', records)
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            QMessageBox.warning(self.surface, '背景设置', '位置已预览，但无法保存设置，请检查文件权限。')
            return False
        return True

    def adjust(self):
        if self.surface.surface_image.isNull() or self.editing:
            return
        from .background_position import BackgroundPositionDialog
        page, label = self.page, self.label
        dialog = BackgroundPositionDialog(self.surface)
        dialog.setWindowTitle('调整背景位置 · ' + label)
        self.editing = True
        try:
            if dialog.exec() == BackgroundPositionDialog.DialogCode.Accepted:
                if self.save_position(page, self.surface.surface_placement):
                    self.notify('已保存“' + label + '”的背景位置，其他页面不变。')
        finally:
            self.editing = False
            dialog.deleteLater()
            # A network response can switch a tab even during a modal preview.
            # Save to the original page, then render whichever page is current.
            self.activate(self.page, self.label)

    def reset_positions(self):
        self.settings.remove(self.key + '_placements')
        self.settings.remove(self.key + '_placement')

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self.surface, '选择背景图片', '',
                                             '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path:
            return
        try:
            save_background(path, self.path)
            self.reset_positions()
            self.reload()
            self.image_changed.emit()
            self.notify('背景已更换；各页的显示区域可分别点击“调整位置”设置。')
        except (ValueError, OSError) as error:
            QMessageBox.warning(self.surface, '背景设置', str(error))

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
            self.reset_positions()
            self.reload()
            self.image_changed.emit()
            self.notify('已恢复默认背景。')
        except OSError:
            QMessageBox.warning(self.surface, '背景设置', '背景无法重置，请检查文件权限。')
