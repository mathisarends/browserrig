"""Optional staging of browser work for people watching it live."""

from .events import (
    SCENE_EVENTS,
    BarTypedEvent,
    CaptureRegion,
    CursorEnteredEvent,
    DomScrolledEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    HighlightElementEvent,
    TabPressedEvent,
    WaitingEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from .plugin import InputVisualization
from .renderer import IframeRenderer
from .stage import Stage
from .tabstrip import TabStrip

__all__ = [
    "DomScrolledEvent",
    "SCENE_EVENTS",
    "BarTypedEvent",
    "CaptureRegion",
    "InputVisualization",
    "IframeRenderer",
    "CursorEnteredEvent",
    "FileTransferEvent",
    "FindBarEvent",
    "FindResultsEvent",
    "HighlightElementEvent",
    "Stage",
    "TabPressedEvent",
    "TabStrip",
    "WaitingEvent",
    "WorkPresentedEvent",
    "WorkPhase",
]
