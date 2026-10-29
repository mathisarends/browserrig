import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from cdpify import CdpClient

from browserrig.events import BrowserEvent, InputEvent

from .models import Download, TabInfo
from .tab import Frame, Tab

type EventSink = Callable[[BrowserEvent | InputEvent], Awaitable[None]]


class Browser(Protocol):
    id: str
    client: CdpClient
    action_lock: asyncio.Lock

    @property
    def active_tab(self) -> Tab: ...

    async def tabs(self) -> tuple[TabInfo, ...]: ...
    async def open_tab(self, url: str = "about:blank") -> Tab: ...
    async def activate_tab(self, target_id: str) -> Tab: ...
    async def close_tab(self, target_id: str) -> None: ...
    async def frames(self, tab: Tab) -> tuple[Frame, ...]: ...
    async def emit(self, event: BrowserEvent | InputEvent) -> None: ...
    async def downloads(self) -> tuple[Download, ...]: ...
