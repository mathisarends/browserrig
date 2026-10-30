import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from browserrig.browser.models import TabInfo
from browserrig.events import BrowserEvent, InputEvent
from browserrig.files import FileSystem
from browserrig.files.models import Download

from .tab import Tab

type EventSink = Callable[[BrowserEvent | InputEvent], Awaitable[None]]


class BrowserEvents:
    """Publish events stamped with the browser that produced them."""

    def __init__(self, browser_id: str, sink: EventSink) -> None:
        self.browser_id = browser_id
        self._sink = sink

    async def emit(self, event: BrowserEvent | InputEvent) -> None:
        await self._sink(replace(event, browser_id=self.browser_id))


class Browser(Protocol):
    # Shared by Observe and Actions; it cannot live in either without a dependency cycle.
    action_lock: asyncio.Lock
    files: FileSystem | None

    @property
    def active_tab(self) -> Tab: ...

    async def tabs(self) -> tuple[TabInfo, ...]: ...
    async def open_tab(self, target: str | Path = "about:blank") -> Tab: ...
    async def activate_tab(self, target_id: str) -> Tab: ...
    async def close_tab(self, target_id: str) -> Tab: ...
    async def downloads(self) -> tuple[Download, ...]: ...
    async def publish_cursor(self) -> None: ...
