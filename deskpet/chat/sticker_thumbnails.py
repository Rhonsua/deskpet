"""Bounded thumbnail decoding for the sticker tray, away from the GUI thread."""
from functools import lru_cache
from pathlib import Path
import threading

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader


@lru_cache(maxsize=256)
def _decode(path, stamp):
    reader = QImageReader(path)
    size = reader.size()
    if (not size.isValid() or max(size.width(), size.height()) > 4096
            or size.width() * size.height() > 12000000):
        return QImage()
    reader.setScaledSize(size.scaled(QSize(64, 64), Qt.KeepAspectRatio))
    return reader.read()


def read_thumbnail(path):
    try:
        info = Path(path).stat()
        return _decode(str(path), (info.st_mtime_ns, info.st_size))
    except OSError:
        return QImage()


class ThumbnailSignals(QObject):
    ready = Signal(int, str, QImage)
    finished = Signal(int)


class ThumbnailJob(QRunnable):
    def __init__(self, generation, entries):
        super().__init__()
        self.generation = generation
        self.entries = entries
        self.stopped = threading.Event()
        self.signals = ThumbnailSignals()

    def run(self):
        try:
            for key, path in self.entries:
                if self.stopped.is_set():
                    break
                image = read_thumbnail(path)
                if not self.stopped.is_set():
                    self.signals.ready.emit(self.generation, key, image)
        finally:
            self.signals.finished.emit(self.generation)
