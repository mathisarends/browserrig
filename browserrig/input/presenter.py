from typing import Protocol

from browserrig.core import Point, TabGesture
from browserrig.events import InputEvent

from .target import InputTarget


class Presenter(Protocol):
    """What viewers see of input; how it is performed is the `Motor`'s concern.

    The devices report what they did. Without a presenter nothing is reported.
    """

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
    """Input nobody watches: nothing is reported or staged."""

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
