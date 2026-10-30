from browserrig.core.modes import CanvasMode, DomMode

from .capture import capture
from .handle import ElementHandle
from .models import Element, Snapshot
from .plugin import Observe
from .render import render

__all__ = [
    "capture",
    "Observe",
    "CanvasMode",
    "DomMode",
    "Element",
    "ElementHandle",
    "Snapshot",
    "render",
]
