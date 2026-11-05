from __future__ import annotations

import asyncio
from dataclasses import asdict
from functools import cache
from importlib.resources import files
from typing import Literal

from pydantic import Field

from browserrig.browser import Overlay, Tab
from browserrig.core import Options
from browserrig.events import BrowserEvent, LiveEvent
from browserrig.scripts import CHOREOGRAPHY


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
        self._overlays: dict[str, Overlay] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def show(self, tab: Tab, event: LiveEvent | BrowserEvent) -> None:
        async with self._lock:
            if self._closed:
                return
            overlay = self._overlays.get(tab.id)
            if overlay is None:
                overlay = await tab.overlays.mount(
                    html=_document(), script=CHOREOGRAPHY
                )
                self._overlays[tab.id] = overlay
            await overlay.send({**asdict(event), "presentation": self._presentation})

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            overlays, self._overlays = self._overlays, {}
            await asyncio.gather(*(overlay.close() for overlay in overlays.values()))


@cache
def _document() -> str:
    package = files(__package__)
    template = package.joinpath("view.html").read_text(encoding="utf-8")
    styles = package.joinpath("view.css").read_text(encoding="utf-8")
    return template.replace("{{styles}}", styles)
