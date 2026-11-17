"""Shared cancellable disk reader for cloud playlist snapshot tabs."""
import threading
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    finished = Signal(int, object, bool)


class _ReadSnapshots(QRunnable):
    def __init__(self, generation, cache, private):
        super().__init__()
        self.generation, self.cache, self.private = generation, cache, private
        self.stopped = threading.Event()
        self.signals = _Signals()

    def run(self):
        rows, failed = [], False
        try:
            for private in ((False, True) if self.private else (False,)):
                if self.stopped.is_set():
                    break
                rows.extend(self.cache.snapshots(private, cancel=self.stopped.is_set))
        except (OSError, ValueError, KeyError, TypeError):
            failed = True
        self.signals.finished.emit(self.generation, rows, failed)


class SnapshotLoader(QObject):
    loaded = Signal(object, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0
        self.active = False
        self.closed = False
        self.jobs = {}

    def cancel(self):
        self.generation += 1
        self.active = False
        for job in self.jobs.values():
            job.stopped.set()

    def start(self, cache, private=False):
        self.cancel()
        if self.closed:
            return
        self.active = True
        job = _ReadSnapshots(self.generation, cache, private)
        self.jobs[self.generation] = job
        job.signals.finished.connect(self._finish)
        QThreadPool.globalInstance().start(job)

    def _finish(self, generation, rows, failed):
        self.jobs.pop(generation, None)
        if generation != self.generation or self.closed:
            return
        self.active = False
        self.loaded.emit(rows, failed)

    def close(self):
        self.closed = True
        self.cancel()
