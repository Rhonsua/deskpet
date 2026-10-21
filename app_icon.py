"""Shared Windows/application icon, resolved in source and PyInstaller bundles."""
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle


def application_icon():
    icon = QIcon(str(Path(__file__).resolve().parent / 'assets' / 'icons' / 'tianyi.ico'))
    if icon.isNull():
        return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
    return icon
