import asyncio
import random
from collections.abc import Callable

from browserrig.core import Point, TabGesture
from browserrig.events import InputEvent
from browserrig.input import CursorPath, InputTarget, movement

from .events import CursorEnteredEvent, TabPressedEvent

# Seconds between keys, in the page and in the browser's own bars.
TYPING_INTERVAL_SECONDS = 0.05
# Travel to the tab strip plus the press, then the way back into the page.
_TAB_PRESS_SECONDS = 0.45
_TAB_ENTER_SECONDS = 0.35


class HumanPace:
    """Input at a person's pace: steady typing, eased pointer paths, visible tab presses.

    Every event goes to the tab it happened in. `action_id` names the current action
    for the events this presenter raises itself.
    """

    def __init__(self, action_id: Callable[[], str]) -> None:
        self._action_id = action_id

    def typing_interval(self) -> float:
        return TYPING_INTERVAL_SECONDS

    def path(self, start: Point, end: Point) -> CursorPath:
        return movement(start, end)

    def landing(self, width: float, height: float) -> Point:
        # Near the middle, but not on the same spot in every tab.
        return Point(
            x=random.uniform(width * 0.4, width * 0.6),
            y=random.uniform(height * 0.4, height * 0.6),
        )

    def shows_cursor_style(self) -> bool:
        return True

    async def leave(
        self, source: InputTarget, gesture: TabGesture, tab_id: str, position: Point
    ) -> None:
        await source.emit(
            TabPressedEvent(
                gesture=gesture,
                tab_id=tab_id,
                from_position=(position.x, position.y),
                duration=_TAB_PRESS_SECONDS,
                action_id=self._action_id(),
            )
        )
        await asyncio.sleep(_TAB_PRESS_SECONDS)

    async def enter(self, target: InputTarget, position: Point) -> None:
        await target.emit(
            CursorEnteredEvent(
                to_position=(position.x, position.y),
                duration=_TAB_ENTER_SECONDS,
                action_id=self._action_id(),
            )
        )
        await asyncio.sleep(_TAB_ENTER_SECONDS)

    async def show(self, target: InputTarget, event: InputEvent) -> None:
        await target.emit(event)
