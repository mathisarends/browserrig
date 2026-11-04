"""Shared values and configuration, independent of browser services."""

from .errors import (
    BrowserClosed,
    BrowserError,
    ReadinessError,
    SecretError,
    StaleElement,
)
from .geometry import Bounds, ElementPoint, FrameTransform, Geometry, Point, Region
from .ids import ActionId, DocumentId, TargetId
from .kinds import (
    ActionKind,
    ActivityKind,
    ActivityOutcome,
    BrowserBar,
    CursorStyle,
    ElementOperation,
    FileSource,
    FileTransferDirection,
    HandoffStatus,
    MouseEventKind,
    ReadinessPhase,
    ReadinessStage,
    ReadinessStatus,
    TabGesture,
)
from .options import Options
from .tools import BrowserToolMetadata, browser_tool

__all__ = [
    "ActionId",
    "ActionKind",
    "ActivityKind",
    "ActivityOutcome",
    "Bounds",
    "BrowserBar",
    "BrowserClosed",
    "BrowserError",
    "BrowserToolMetadata",
    "CursorStyle",
    "DocumentId",
    "ElementOperation",
    "ElementPoint",
    "FileSource",
    "FileTransferDirection",
    "FrameTransform",
    "Geometry",
    "HandoffStatus",
    "MouseEventKind",
    "Options",
    "Point",
    "ReadinessError",
    "ReadinessPhase",
    "ReadinessStage",
    "ReadinessStatus",
    "Region",
    "SecretError",
    "StaleElement",
    "TabGesture",
    "TargetId",
    "browser_tool",
]
