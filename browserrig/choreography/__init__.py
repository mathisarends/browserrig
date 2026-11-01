"""Optional staging of browser work for people watching it live."""

from .events import (
    SCENE_EVENTS,
    BarTypedEvent,
    CursorEnteredEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    HighlightElementEvent,
    TabPressedEvent,
    WaitingEvent,
)
from .plugin import Choreography
from .stage import Stage
from .tabstrip import TabStrip

__all__ = [
    "SCENE_EVENTS",
    "BarTypedEvent",
    "Choreography",
    "CursorEnteredEvent",
    "FileTransferEvent",
    "FindBarEvent",
    "FindResultsEvent",
    "HighlightElementEvent",
    "Stage",
    "TabPressedEvent",
    "TabStrip",
    "WaitingEvent",
]
