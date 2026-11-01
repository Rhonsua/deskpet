"""Trusted, explicitly registered desktop companion extensions."""
from .api import Mod, ModContext, ModManifest
from .manager import ModManager
from . import api
from deskpet.ui import theme
import sys

# Published Mod ZIPs used this API path before the source folders were grouped.
# Both names must refer to the same classes, including in the frozen loader.
sys.modules.setdefault('pet_mods', sys.modules[__name__])
sys.modules.setdefault('pet_mods.api', api)
# Goal Companion 0.1.0 used this shared UI module in its public ZIP.
sys.modules.setdefault('ui_theme', theme)

__all__ = ['Mod', 'ModContext', 'ModManifest', 'ModManager']
