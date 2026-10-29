from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import replace

from cdpify import CdpSession

from browserrig.events import InputEvent

from .keyboard import Keyboard
from .mouse import Mouse


class Input:
    """Share action correlation across a tab's independent mouse and keyboard controllers."""

    def __init__(self, cdp: CdpSession, emit: Callable[[InputEvent], Awaitable[None]]) -> None:
        self._emit = emit
        self._action_id = ""
        self.mouse = Mouse(cdp, emit=self.emit)
        self.keyboard = Keyboard(cdp, emit=self.emit)

    @contextmanager
    def action(self, action_id: str):
        previous, self._action_id = self._action_id, action_id
        try:
            yield
        finally:
            self._action_id = previous

    async def emit(self, event: InputEvent) -> None:
        await self._emit(replace(event, action_id=self._action_id))
