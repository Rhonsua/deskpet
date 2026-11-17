"""Cancellable playlist file checks; results always return on the UI thread."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(int, object)


class _Job(QRunnable):
    def __init__(self, ticket, paths):
        super().__init__()
        self.ticket, self.paths = ticket, paths
        self.stopped = threading.Event()
        self.signals = _Signals()

    def run(self):
        results = {}
        try:
            for path in self.paths:
                if self.stopped.is_set():
                    break
                try:
                    results[path] = Path(path).is_file()
                except OSError:
                    results[path] = False
        finally:
            self.signals.done.emit(self.ticket, results)


class FileAvailability(QObject):
    ready = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ticket = 0
        self.jobs = {}

    def start(self, paths):
        for job in self.jobs.values():
            job.stopped.set()
        self.ticket += 1
        job = _Job(self.ticket, tuple(paths))
        self.jobs[self.ticket] = job
        job.signals.done.connect(self._finish)
        QThreadPool.globalInstance().start(job)
        return self.ticket

    def _finish(self, ticket, results):
        self.jobs.pop(ticket, None)
        if ticket == self.ticket:
            self.ready.emit(ticket, results)
