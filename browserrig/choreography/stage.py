import asyncio
from collections.abc import Callable

from browserrig.core import Point, TabGesture
from browserrig.events import InputEvent
from browserrig.input import InputTarget

from .events import CursorEnteredEvent, TabPressedEvent

# Travel to the tab strip plus the press, then the way back into the page.
_TAB_PRESS_SECONDS = 0.45
_TAB_ENTER_SECONDS = 0.35


class Stage:
    """Input as people watching see it: cursor shapes and visible tab presses.

    Every event goes to the tab it happened in. `action_id` names the current action
    for the events this presenter raises itself. How fast input runs is up to the motor.
    """

    def __init__(self, action_id: Callable[[], str]) -> None:
        self._action_id = action_id

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
