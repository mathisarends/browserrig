"""Shared values, configuration and coordination, independent of browser backends."""

from .actions import ActionContext
from .coordination import BrowserCoordination
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
from .model_profiles import MODEL_PROFILES, ModelProfile
from .options import Options
from .runtime import Runtime
from .tabs import ChangeTab, TabDispatch
from .tools import BrowserToolCall, BrowserToolMetadata, browser_tool

__all__ = [
    "ActionContext",
    "Runtime",
    "ChangeTab",
    "TabDispatch",
    "MODEL_PROFILES",
    "ModelProfile",
    "BrowserCoordination",
    "ActionId",
    "ActionKind",
    "ActivityKind",
    "ActivityOutcome",
    "Bounds",
    "BrowserBar",
    "BrowserClosed",
    "BrowserError",
    "BrowserToolMetadata",
    "BrowserToolCall",
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
