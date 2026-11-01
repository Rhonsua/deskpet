"""Qt-free contracts for trusted local mods."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


@dataclass(frozen=True)
class ModManifest:
    id: str
    name: str
    version: str
    description: str = ''
    api_version: int = 1


@dataclass(frozen=True)
class ModContext:
    data_dir: Path
    notify: Callable[[str], bool]


class Mod(Protocol):
    def start(self) -> None: ...
    def tick(self, now: datetime) -> None: ...
    def stop(self) -> None: ...
    def create_widget(self, parent=None): ...
