from browserrig.core.modes import CanvasMode, DomMode

from .capture import CanvasCapture, CaptureContent, CaptureStrategy, DomCapture, capture
from .config import Screenshots, ScreenshotTrigger
from .handle import ElementHandle
from .images import ImageContext, ImageRetention, TrimInBatches, UntilCompaction
from .models import CapturedImage, Element, Snapshot
from .plugin import Observe
from .regions import CanvasRegion, CaptureRegion
from .render import render
from .renderer import CanvasRenderer, DomRenderer, Renderer

__all__ = [
    "CanvasCapture",
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
    "CanvasRegion",
    "CaptureRegion",
    "CanvasRenderer",
    "DomRenderer",
    "Renderer",
    "capture",
    "Observe",
    "CanvasMode",
    "DomMode",
    "Element",
    "ElementHandle",
    "Snapshot",
    "render",
]
