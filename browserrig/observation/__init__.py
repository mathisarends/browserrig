from browserrig.core.modes import DomMode

from .capture import CaptureContent, CaptureStrategy, DomCapture, capture
from .config import Screenshots, ScreenshotTrigger
from .handle import ElementHandle
from .images import ImageContext, ImageRetention, TrimInBatches, UntilCompaction
from .models import CapturedImage, Element, Snapshot
from .plugin import Observe
from .render import render
from .renderer import DomRenderer, Renderer

__all__ = [
    "CaptureContent",
    "CaptureStrategy",
    "DomCapture",
    "Screenshots",
    "ScreenshotTrigger",
    "ImageContext",
    "ImageRetention",
    "TrimInBatches",
    "UntilCompaction",
    "CapturedImage",
    "DomRenderer",
    "Renderer",
    "capture",
    "Observe",
    "DomMode",
    "Element",
    "ElementHandle",
    "Snapshot",
    "render",
]
