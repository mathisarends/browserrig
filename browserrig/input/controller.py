import asyncio
from contextlib import contextmanager
from dataclasses import replace

from browserrig.core.geometry import Bounds, Point
from browserrig.core.kinds import FileTransferDirection
from browserrig.events import FileTransferEvent, HighlightElementEvent, InputEvent

from .keyboard import Keyboard
from .mouse import Mouse
from .target import Focus, InputTarget, focused

# Long enough for a viewer to follow a file into its destination, short enough to stay brisk.
_TRANSFER_SECONDS = 0.45


class Input:
    """The browser's mouse and keyboard, aimed at whichever tab has focus.

    It also correlates every input event with the action that caused it.
    """

    def __init__(self, focus: Focus) -> None:
        self._focus = focus
        self._action_id = ""
        self.mouse = Mouse(focus, emit=self._emit)
        self.keyboard = Keyboard(focus, emit=self._emit)

    @property
    def action_id(self) -> str:
        return self._action_id

    @contextmanager
    def action(self, action_id: str):
        previous, self._action_id = self._action_id, action_id
        try:
            yield
        finally:
            self._action_id = previous

    async def highlight(self, ref: str, bounds: Bounds) -> None:
        """Show which element the next input targets, for live viewers."""
        await self._emit(
            focused(self._focus),
            HighlightElementEvent(
                ref=ref, x=bounds.x, y=bounds.y, width=bounds.width, height=bounds.height
            ),
        )

    async def transfer(
        self,
        direction: FileTransferDirection,
        paths: tuple[str, ...],
        point: Point | None = None,
    ) -> None:
        """Announce files moving into a tab or onto `point`, then hold for the animation."""
        await self._emit(
            focused(self._focus),
            FileTransferEvent(
                direction=direction,
                paths=paths,
                duration=_TRANSFER_SECONDS,
                x=point.x if point is not None else None,
                y=point.y if point is not None else None,
            ),
        )
        await asyncio.sleep(_TRANSFER_SECONDS)

    async def _emit(self, target: InputTarget, event: InputEvent) -> None:
        await target.emit(replace(event, action_id=self._action_id))
