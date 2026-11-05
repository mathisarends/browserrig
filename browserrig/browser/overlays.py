"""Browser-owned presentation surfaces, independent of their consumers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.core import BrowserError
from browserrig.events import PageCaptureFinishedEvent, PageCaptureStartedEvent
from browserrig.scripts import OVERLAY, OVERLAY_STYLES, OverlayArgs, Script, ScriptArgs

from .frame import Frame

if TYPE_CHECKING:
    from .tab import Tab


class Overlays:
    """Own inert iframe surfaces and omit them from ordinary page screenshots.

    Surfaces are registered by DOM identity in the browser's isolated world. They
    never receive focus or pointer input. Each handle restores its surface after
    navigation when next sent data; closing a handle never installs it again.
    """

    def __init__(self, tab: Tab) -> None:
        self._tab = tab
        self._items: dict[str, _Surface] = {}
        self._lock = asyncio.Lock()

    async def mount(
        self, *, html: str, script: Script[ScriptArgs, None] | None = None
    ) -> Overlay:
        """Mount trusted application HTML/JS, outside page observation and input."""
        surface = _Surface(uuid4().hex, html, script)
        async with self._lock:
            try:
                await self._run(surface, "mount")
            except BaseException:
                with suppress(BrowserError):
                    await self._run(surface, "close")
                raise
            self._items[surface.id] = surface
            self._tab.layout_changed()
        return Overlay(
            surface.id,
            partial(self._send, surface.id),
            partial(self._close, surface.id),
        )

    @asynccontextmanager
    async def hidden(self) -> AsyncGenerator[None]:
        """Exclude surfaces for a capture, with awaited browser lifecycle receipts.

        Recording subscribers can stop before hiding and resume after restoration.
        The lock keeps concurrent screenshots and presentation updates coherent.
        """
        async with self._lock:
            if not self._items:
                yield
                return
            capture_id = uuid4().hex
            try:
                await self._tab.emit(PageCaptureStartedEvent(capture_id=capture_id))
                await self._visibility(False)
                yield
            finally:
                try:
                    await self._visibility(True)
                finally:
                    await self._tab.emit(
                        PageCaptureFinishedEvent(capture_id=capture_id)
                    )

    async def _send(self, overlay_id: str, data: Any) -> None:
        async with self._lock:
            surface = self._items.get(overlay_id)
            if surface is not None and not self._tab.closed:
                await self._run(surface, "send", data)

    async def _close(self, overlay_id: str) -> None:
        async with self._lock:
            surface = self._items.pop(overlay_id, None)
            if surface is not None and not self._tab.closed:
                await self._run(surface, "close")
                self._tab.layout_changed()

    async def _run(self, overlay: _Surface, operation: str, data: Any = None) -> None:
        try:
            await self._apply(overlay, operation, data)
        except CDPCommandError as error:
            raise BrowserError(
                "Browser overlay unavailable for this document"
            ) from error

    async def _apply(self, overlay: _Surface, operation: str, data: Any) -> None:
        frame = await self._tab.main_frame()
        if operation == "close":
            await frame.run(OVERLAY, OverlayArgs(operation=operation, id=overlay.id))
            return
        mounted = await frame.run(
            OVERLAY, OverlayArgs(operation="mount", id=overlay.id)
        )
        if mounted or overlay.document_id != frame.document_id:
            tree = await self._tab.frame_tree()
            child = next(
                (
                    child.frame
                    for child in tree.child_frames or ()
                    if child.frame.name == f"browserrig-overlay-{overlay.id}"
                ),
                None,
            )
            if child is None:
                raise BrowserError("Browser overlay frame is no longer available")
            surface = Frame(
                child.id,
                self._tab.cdp,
                document_id=child.loader_id,
                worlds=self._tab.worlds,
            )
            # CDP populates the initial blank document and runs trusted code in
            # its isolated world, without changing the inspected page's CSP.
            await surface.cdp.page.set_document_content(
                frame_id=child.id, html=overlay.html
            )
            await surface.run(OVERLAY_STYLES)
            if overlay.script is not None:
                await surface.run(overlay.script)
            overlay.document_id = frame.document_id
        if operation == "mount":
            return
        await frame.run(
            OVERLAY,
            OverlayArgs(
                operation=operation,
                id=overlay.id,
                data=data,
            ),
        )

    async def _visibility(self, visible: bool) -> None:
        if self._tab.closed:
            return
        frame = await self._tab.main_frame()
        await frame.run(OVERLAY, OverlayArgs(operation="visibility", visible=visible))


class Overlay:
    """One application-owned surface; data crosses into its sandbox via messages."""

    def __init__(
        self,
        overlay_id: str,
        send: Callable[[Any], Awaitable[None]],
        close: Callable[[], Awaitable[None]],
    ) -> None:
        self.id = overlay_id
        self._send = send
        self._close = close

    async def send(self, data: Any) -> None:
        """Deliver JSON data, remounting in a new document when necessary."""
        await self._send(data)

    async def close(self) -> None:
        """Remove the surface and release its registration, once."""
        await self._close()


@dataclass(slots=True)
class _Surface:
    id: str
    html: str
    script: Script[ScriptArgs, None] | None
    document_id: str = ""
