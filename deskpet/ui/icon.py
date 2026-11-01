"""Shared Windows/application icon, resolved in source and PyInstaller bundles."""
from pathlib import Path
from deskpet.paths import RESOURCE_ROOT

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle


def application_icon():
    icon = QIcon(str(RESOURCE_ROOT / 'assets' / 'icons' / 'tianyi.ico'))
    if icon.isNull():
        return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
    return icon
