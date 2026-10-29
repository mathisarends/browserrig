import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from cdpify import CdpClient

from browserrig.browser.models import TabInfo
from browserrig.events import BrowserEvent, InputEvent
from browserrig.files import FileSystem
from browserrig.files.models import Download

from .tab import Frame, Tab

type EventSink = Callable[[BrowserEvent | InputEvent], Awaitable[None]]


class Browser(Protocol):
    id: str
    client: CdpClient
    action_lock: asyncio.Lock
    files: FileSystem | None

    @property
    def active_tab(self) -> Tab: ...

    async def tabs(self) -> tuple[TabInfo, ...]: ...
    async def open_tab(self, url: str = "about:blank") -> Tab: ...
    async def open_file(self, path: str) -> Tab: ...
    async def activate_tab(self, target_id: str) -> Tab: ...
    async def close_tab(self, target_id: str) -> Tab: ...
    async def frames(self, tab: Tab) -> tuple[Frame, ...]: ...
    async def emit(self, event: BrowserEvent | InputEvent) -> None: ...
    async def downloads(self) -> tuple[Download, ...]: ...
    async def publish_cursor(self) -> None: ...
