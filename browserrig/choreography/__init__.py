"""Optional staging of browser work for people watching it live."""

from .events import (
    SCENE_EVENTS,
    AddressBarFocusedEvent,
    BackPressedEvent,
    BarTypedEvent,
    CaptureRegion,
    CursorEnteredEvent,
    ElementScrolledEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    ForwardPressedEvent,
    HighlightElementEvent,
    PageScrolledEvent,
    ReloadPressedEvent,
    TabPressedEvent,
    ToolbarPressedEvent,
    WaitingEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from .plugin import InputVisualization
from .renderer import IframeRenderer
from .stage import Stage
from .tabstrip import TabStrip

__all__ = [
    "ElementScrolledEvent",
    "PageScrolledEvent",
    "SCENE_EVENTS",
    "AddressBarFocusedEvent",
    "BackPressedEvent",
    "BarTypedEvent",
    "CaptureRegion",
    "InputVisualization",
    "IframeRenderer",
    "CursorEnteredEvent",
    "FileTransferEvent",
    "FindBarEvent",
    "FindResultsEvent",
    "ForwardPressedEvent",
    "HighlightElementEvent",
    "ReloadPressedEvent",
    "Stage",
    "TabPressedEvent",
    "TabStrip",
    "ToolbarPressedEvent",
    "WaitingEvent",
    "WorkPresentedEvent",
    "WorkPhase",
]
