from __future__ import annotations

import asyncio
from dataclasses import asdict
from functools import cache
from importlib.resources import files
from typing import Literal

from harnessed.tracing import traced
from pydantic import Field

from browserrig.browser import Overlay, Tab
from browserrig.core import ActionKind, ActivityKind, Options
from browserrig.events import BrowserEvent, EventKind, LiveEvent
from browserrig.scripts import CHOREOGRAPHY

from .events import WorkPhase
from .receipts import Receipts


class IframeRenderer(Options):
    """Configure a transparent, inert browser-owned input visualization."""

    name: str = Field(default="Browserrig", min_length=1, max_length=40)
    keyboard_layout: Literal["en", "de"] = "en"
    theme: Literal["dark", "light", "auto"] = "dark"

    def create(self) -> IframeView:
        """Create fresh presentation state for one session."""
        return IframeView(self)


class IframeView:
    def __init__(self, options: IframeRenderer) -> None:
        self._presentation = options.model_dump(mode="json")
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
        self._shown: tuple[str, str] | None = None

    def remember(self, event: LiveEvent | BrowserEvent) -> None:
        """Retain receipts even when the document cannot currently render them."""
        self._receipts.remember(event)

    def suspend(self) -> None:
        """Request state restoration after a dialog or unavailable document."""
        self._shown = None

    async def restore(self, tab: Tab) -> None:
        """Restore state without inventing a browser input event."""
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
            identity = (tab.id, tab.document_id)
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
