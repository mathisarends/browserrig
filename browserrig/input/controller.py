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
        self.tab = tab
        self.action_id = ""
        self.mouse = Mouse(tab, emit=self.emit)
        self.keyboard = Keyboard(tab, emit=self.emit)

    @contextmanager
    def action(self, action_id: str):
        previous, self.action_id = self.action_id, action_id
        try:
            yield
        finally:
            self.action_id = previous

    async def emit(self, event: InputEvent) -> None:
        await self.tab.emit(replace(event, action_id=self.action_id))
