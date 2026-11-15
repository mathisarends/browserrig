from __future__ import annotations

import asyncio
from dataclasses import asdict
from functools import cache
from importlib.resources import files
from typing import Literal, NamedTuple

from harnessed.tracing import traced
from pydantic import Field

from browserrig.browser import Overlay, Tab
from browserrig.choreography import WorkPhase
from browserrig.core import ActionKind, ActivityKind, Options
from browserrig.events import BrowserEvent, EventKind, LiveEvent
from browserrig.scripts import CHOREOGRAPHY

from .receipts import Receipts

type KeyboardLayout = Literal["en", "de"]
type Theme = Literal["dark", "light", "auto"]


class OverlayStyle(Options):
    """How the in-page overlay labels the cursor, lays out keys and colors itself."""

    name: str = Field(default="Browserrig", min_length=1, max_length=40)
    keyboard_layout: KeyboardLayout = "en"
    theme: Theme = "dark"


class OverlayView:
    """One session's iframe per tab, fed with serialized receipts."""

    def __init__(self, style: OverlayStyle) -> None:
        self._presentation = style.model_dump(mode="json")
        self._presentation["events"] = {kind.name: kind.value for kind in EventKind}
        self._presentation["phases"] = {phase.name: phase.value for phase in WorkPhase}
        self._presentation["actions"] = {kind.name: kind.value for kind in ActionKind}
        self._presentation["activities"] = {
            kind.name: kind.value for kind in ActivityKind
        }
        self._overlays: dict[str, Overlay] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._receipts = Receipts()
        self._shown: _Document | None = None

    def remember(self, event: LiveEvent | BrowserEvent) -> None:
        """Retain receipts even when the document cannot currently render them."""
        self._receipts.remember(event)

    def suspend(self) -> None:
        """Request state restoration after a dialog or unavailable document."""
        self._shown = None

    async def restore(self, tab: Tab) -> None:
        """Redraw retained receipts in a document that has not shown them yet."""
        if _Document(tab.id, tab.document_id) != self._shown:
            await self._show(tab, None)

    async def show(self, tab: Tab, event: LiveEvent | BrowserEvent) -> None:
        self.remember(event)
        await self._show(tab, event)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            overlays, self._overlays = self._overlays, {}
            await asyncio.gather(*(overlay.close() for overlay in overlays.values()))

    @traced
    async def _show(self, tab: Tab, event: LiveEvent | BrowserEvent | None) -> None:
        async with self._lock:
            if self._closed:
                return
            overlay = self._overlays.get(tab.id)
            if overlay is None:
                overlay = await tab.overlays.mount(
                    html=_document(), script=CHOREOGRAPHY
                )
                self._overlays[tab.id] = overlay
            identity = _Document(tab.id, tab.document_id)
            data = asdict(event) if event is not None else {}
            data["presentation"] = {
                **self._presentation,
                "target_id": tab.id,
                "document_id": tab.document_id,
            }
            if identity != self._shown:
                data["restore"] = [
                    asdict(receipt) for receipt in self._receipts.snapshot()
                ]
            await overlay.send(data)
            self._shown = identity


@cache
def _document() -> str:
    package = files(__package__)
    template = package.joinpath("view.html").read_text(encoding="utf-8")
    styles = package.joinpath("view.css").read_text(encoding="utf-8")
    return template.replace("{{styles}}", styles)


class _Document(NamedTuple):
    target_id: str
    document_id: str
