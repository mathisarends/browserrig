"""How fast and in what way the browser's mouse and keyboard are operated."""

from .planners import KeystrokePlanner, PointerRoutePlanner
from .plugin import InputPacing

__all__ = ["InputPacing", "KeystrokePlanner", "PointerRoutePlanner"]
