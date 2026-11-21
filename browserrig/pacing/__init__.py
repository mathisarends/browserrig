"""How fast and in what way the browser's mouse and keyboard are operated."""

from .planners import CursorRoutePlanner, KeystrokePlanner
from .plugin import InputPacing

__all__ = ["InputPacing", "KeystrokePlanner", "CursorRoutePlanner"]
