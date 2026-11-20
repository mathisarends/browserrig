import asyncio

from browserrig.core import Point, Position, TabGesture
from browserrig.events import InputEvent, KeyboardVisibilityEvent, KeyPressedEvent
from browserrig.input import InputTarget

from .events import CursorEnteredEvent, TabPressedEvent

# Travel to the browser's own controls plus the press, then the way back into the page.
PRESS_SECONDS = 0.45
ENTER_SECONDS = 0.35


class Stage:
    """Input as people watching see it: cursor shapes and visible tab presses.

    Every event goes to the tab it happened in, correlated with the action that `Input`
    reports. How fast input runs is up to the motor.
    """

    def __init__(
        self, *, pointer: bool = True, keyboard: bool = True, tabs: bool = True
    ) -> None:
        self._pointer = pointer
        self._keyboard = keyboard
        self._tabs = tabs

    def shows_cursor_style(self) -> bool:
        return self._pointer

    async def leave(
        self,
        source: InputTarget,
        gesture: TabGesture,
        tab_id: str,
        position: Point,
        *,
        action_id: str,
    ) -> None:
        if not self._tabs:
            return
        await source.emit(
            TabPressedEvent(
                gesture=gesture,
                tab_id=tab_id,
                from_position=Position(position.x, position.y),
                duration_seconds=PRESS_SECONDS,
                action_id=action_id,
            )
        )
        await asyncio.sleep(PRESS_SECONDS)

    async def enter(
        self, target: InputTarget, position: Point, *, action_id: str
    ) -> None:
        if not self._tabs:
            return
        await target.emit(
            CursorEnteredEvent(
                to_position=Position(position.x, position.y),
                duration_seconds=ENTER_SECONDS,
                action_id=action_id,
            )
        )
        await asyncio.sleep(ENTER_SECONDS)

    async def show(self, target: InputTarget, event: InputEvent) -> None:
        enabled = (
            self._keyboard
            if isinstance(event, (KeyboardVisibilityEvent, KeyPressedEvent))
            else self._pointer
        )
        if enabled:
            await target.emit(event)
