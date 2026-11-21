"""Public event and operation enums."""

from .core import (
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

__all__ = [  # smelt: ignore[VIS003] -- browserrig.kinds is a public compatibility facade
    "ActionKind",
    "ActivityKind",
    "ActivityOutcome",
    "BrowserBar",
    "CursorStyle",
    "ElementOperation",
    "FileSource",
    "FileTransferDirection",
    "HandoffStatus",
    "MouseEventKind",
    "ReadinessPhase",
    "ReadinessStage",
    "ReadinessStatus",
    "TabGesture",
]
