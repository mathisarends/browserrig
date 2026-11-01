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
from .pacing import TYPING_INTERVAL_SECONDS, HumanPace
from .plugin import Choreography
from .tabstrip import TabStrip

__all__ = [
    "SCENE_EVENTS",
    "TYPING_INTERVAL_SECONDS",
    "BarTypedEvent",
    "Choreography",
    "CursorEnteredEvent",
    "FileTransferEvent",
    "FindBarEvent",
    "FindResultsEvent",
    "HighlightElementEvent",
    "HumanPace",
    "TabPressedEvent",
    "TabStrip",
    "WaitingEvent",
]
