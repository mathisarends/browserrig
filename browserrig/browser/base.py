from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Protocol

from browserrig.events import BrowserEvent, LiveEvent
from browserrig.files import Download, FileTransfer

from .tab import Tab

if TYPE_CHECKING:
    from .tabs import Tabs

type EventSink = Callable[[BrowserEvent | LiveEvent], Awaitable[None]]
type EventFilter = Callable[[BrowserEvent | LiveEvent], BrowserEvent | LiveEvent]


class BrowserEvents:
    """Publish events stamped with the browser that produced them.

    Filters rewrite each event before it reaches the sink, e.g. to redact secrets.
    """

    def __init__(self, browser_id: str, sink: EventSink) -> None:
        self.browser_id = browser_id
        self._sink = sink
        self._filters: list[EventFilter] = []

    def add_filter(self, event_filter: EventFilter) -> Callable[[], None]:
        """Apply `event_filter` to later events; the returned callable removes it."""
        self._filters.append(event_filter)

        def remove() -> None:
            if event_filter in self._filters:
                self._filters.remove(event_filter)

        return remove

    async def emit(self, event: BrowserEvent | LiveEvent) -> None:
        event = replace(event, browser_id=self.browser_id)
        for event_filter in tuple(self._filters):
            event = event_filter(event)
        await self._sink(event)


class Browser(Protocol):
    tabs: Tabs

    @property
    def active_tab(self) -> Tab: ...

    async def downloads(self) -> tuple[Download, ...]: ...

    async def receive_downloads(self, transfer: FileTransfer | None) -> bool:
        """Save later downloads through `transfer`; return whether they are received."""
        ...


async def _discard(_event: BrowserEvent | LiveEvent) -> None:
    pass
