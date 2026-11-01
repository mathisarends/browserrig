from typing import Protocol

from browserrig.core import Point, TabGesture
from browserrig.events import InputEvent

from .pointer import CursorPath
from .target import InputTarget


class Presenter(Protocol):
    """How input looks to viewers: how fast it goes and what they are told.

    The devices ask it for pacing and report what they did. Without one, input runs as
    fast as the page accepts it and nothing is reported.
    """

    def typing_interval(self) -> float:
        """Seconds between keys typed into the page."""
        ...

    def path(self, start: Point, end: Point) -> CursorPath:
        """The pointer's way from `start` to `end`; its duration paces the native moves."""
        ...

    def landing(self, width: float, height: float) -> Point:
        """Where the pointer first appears in a tab whose viewport has this size."""
        ...

    def shows_cursor_style(self) -> bool:
        """Whether to ask the page which cursor shape the pointer rests on."""
        ...

    async def leave(
        self, source: InputTarget, gesture: TabGesture, tab_id: str, position: Point
    ) -> None:
        """The pointer leaves `source` at `position` for a tab-strip control."""
        ...

    async def enter(self, target: InputTarget, position: Point) -> None:
        """After a tab-strip control, the pointer returns into `target` at `position`."""
        ...

    async def show(self, target: InputTarget, event: InputEvent) -> None:
        """Report input that happened in `target`'s tab."""
        ...


class Unseen:
    """Input nobody watches: no pauses, straight pointer moves, nothing reported."""

    def typing_interval(self) -> float:
        return 0

    def path(self, start: Point, end: Point) -> CursorPath:
        return CursorPath(start, end, 0)

    def landing(self, width: float, height: float) -> Point:
        return Point(x=width / 2, y=height / 2)

    def shows_cursor_style(self) -> bool:
        return False

    async def leave(
        self, source: InputTarget, gesture: TabGesture, tab_id: str, position: Point
    ) -> None:
        pass

    async def enter(self, target: InputTarget, position: Point) -> None:
        pass

    async def show(self, target: InputTarget, event: InputEvent) -> None:
        pass
