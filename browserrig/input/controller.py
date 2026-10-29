from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING

from browserrig.events import InputEvent

from .keyboard import Keyboard
from .mouse import Mouse

if TYPE_CHECKING:
    from browserrig.browser.tab import Tab


class Input:
    """Share action correlation across a tab's independent mouse and keyboard controllers."""

    def __init__(self, tab: Tab) -> None:
        self._tab = tab
        self._action_id = ""
        self.mouse = Mouse(tab, emit=self.emit)
        self.keyboard = Keyboard(tab, emit=self.emit)

    @contextmanager
    def action(self, action_id: str):
        previous, self._action_id = self._action_id, action_id
        try:
            yield
        finally:
            self._action_id = previous

    async def emit(self, event: InputEvent) -> None:
        await self._tab.emit(replace(event, action_id=self._action_id))
