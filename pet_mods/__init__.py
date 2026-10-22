"""Trusted, explicitly registered desktop companion extensions."""
from .api import Mod, ModContext, ModManifest
from .manager import ModManager

__all__ = ['Mod', 'ModContext', 'ModManifest', 'ModManager']
