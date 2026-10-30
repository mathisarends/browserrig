from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import replace

from cdpify import CdpSession

from browserrig.core.geometry import Bounds, Point
from browserrig.core.kinds import CursorStyle, FileTransferDirection
from browserrig.events import FileTransferEvent, HighlightElementEvent, InputEvent

from .keyboard import Keyboard
from .mouse import Mouse

# Long enough for a viewer to follow a file into its destination, short enough to stay brisk.
_TRANSFER_SECONDS = 0.45


class Input:
    """Share action correlation across a tab's independent mouse and keyboard controllers."""

    def __init__(
        self,
        cdp: CdpSession,
        emit: Callable[[InputEvent], Awaitable[None]],
        *,
        layout_changed: Callable[[], None] = lambda: None,
        cursor_style: Callable[[Point], Awaitable[CursorStyle | None]] | None = None,
    ) -> None:
        self._sink = emit
        self._action_id = ""
        self.mouse = Mouse(
            cdp, emit=self._emit, layout_changed=layout_changed, cursor_style=cursor_style
        )
        self.keyboard = Keyboard(cdp, emit=self._emit)

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
        """Show which element the next input targets, for recordings and live viewers."""
        await self._emit(
            HighlightElementEvent(
                ref=ref, x=bounds.x, y=bounds.y, width=bounds.width, height=bounds.height
            )
        )

    async def transfer(
        self,
        direction: FileTransferDirection,
        paths: tuple[str, ...],
        point: Point | None = None,
    ) -> None:
        """Announce files moving into a tab or onto `point`, then hold for the animation."""
        await self._emit(
            FileTransferEvent(
                direction=direction,
                paths=paths,
                duration=_TRANSFER_SECONDS,
                x=point.x if point is not None else None,
                y=point.y if point is not None else None,
            )
        )
        await asyncio.sleep(_TRANSFER_SECONDS)

    async def _emit(self, event: InputEvent) -> None:
        await self._sink(replace(event, action_id=self._action_id))
