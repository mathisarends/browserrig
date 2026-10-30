"""Computed styles requested with every DOM snapshot.

DOMSnapshot returns each layout node's styles as a list ordered like the request,
so values are addressed by position. Members are declared in request order.
"""

from enum import StrEnum


class Style(StrEnum):
    VISIBILITY = "visibility"
    OPACITY = "opacity"
    OVERFLOW_X = "overflow-x"
    OVERFLOW_Y = "overflow-y"
    CURSOR = "cursor"
    POINTER_EVENTS = "pointer-events"
    POSITION = "position"
    BACKGROUND_COLOR = "background-color"
    CLIP_PATH = "clip-path"
    CLIP = "clip"
    DISPLAY = "display"

    @property
    def slot(self) -> int:
        """Position of this style in each node's computed style list."""
        return _SLOTS[self]


STYLES: tuple[str, ...] = tuple(Style)
_SLOTS = {style: slot for slot, style in enumerate(Style)}
