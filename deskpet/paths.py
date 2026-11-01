"""Stable data/launcher roots, independent of Python module organization."""
from pathlib import Path
import sys

PROJECT_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
                else Path(__file__).resolve().parent.parent)
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', PROJECT_ROOT))
