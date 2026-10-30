from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import replace

from cdpify import CdpSession

from browserrig.core.geometry import Bounds
from browserrig.events import HighlightElementEvent, InputEvent

from .keyboard import Keyboard
from .mouse import Mouse


class Input:
    """Share action correlation across a tab's independent mouse and keyboard controllers."""

    def __init__(
        self,
        cdp: CdpSession,
        emit: Callable[[InputEvent], Awaitable[None]],
        *,
        layout_changed: Callable[[], None] = lambda: None,
    ) -> None:
        self._sink = emit
        self._action_id = ""
        self.mouse = Mouse(cdp, emit=self._emit, layout_changed=layout_changed)
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

    async def _emit(self, event: InputEvent) -> None:
        await self._sink(replace(event, action_id=self._action_id))
