"""Run all unit tests with one GUI application (also covers QCoreApplication tests)."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    suite = (unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]) if len(sys.argv) > 1
             else unittest.defaultTestLoader.discover(str(ROOT / 'tests')))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
