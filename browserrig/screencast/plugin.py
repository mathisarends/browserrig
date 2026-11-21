import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Literal

from cdpify import CDPError
from cdpify.domains.page import ScreencastFrameEvent
from harnessed import Plugin
from harnessed.kernel import PluginScope, PluginState, hook, needs
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import BrowserError, Options
from browserrig.events import TabActivatedEvent, TabClosedEvent

from .models import ScreencastFrame

type _ImageFormat = Literal["jpeg", "png"]


class _Settings(Options):
    image_format: _ImageFormat
    quality: int | None = Field(ge=0, le=100)
    max_width: int = Field(gt=0)
    max_height: int = Field(gt=0)


class _Stream:
    def __init__(self, settings: _Settings, tab: Tab | None) -> None:
        self._settings = settings
        self._tab = tab
        self._tab_changed = asyncio.Event()
        self._frame_ready = asyncio.Event()
        self._latest: ScreencastFrame | None = None
        self._failure: Exception | None = None
        self._closed = False
        self._worker = asyncio.create_task(self._run(), name="browserrig:screencast")

    async def frames(self) -> AsyncGenerator[ScreencastFrame]:
        while not self._closed:
            await self._frame_ready.wait()
            self._frame_ready.clear()
            if (frame := self._latest) is not None:
                self._latest = None
                yield frame
        if self._failure is not None:
            raise BrowserError("Live screencast failed") from self._failure

    def follow(self, tab: Tab | None) -> None:
        if self._closed or tab is self._tab:
            return
        self._tab = tab
        self._latest = None
        self._tab_changed.set()

    async def close(self) -> None:
        self._finish()
        self._tab_changed.set()
        await asyncio.shield(self._worker)

    async def _run(self) -> None:
        try:
            while not self._closed:
                self._tab_changed.clear()
                if self._tab is None:
                    await self._tab_changed.wait()
                else:
                    await self._follow_tab(self._tab)
        finally:
            self._finish()

    async def _follow_tab(self, tab: Tab) -> None:
        async with asyncio.TaskGroup() as group:
            capture = group.create_task(self._capture(tab))
            await self._tab_changed.wait()
            capture.cancel()

    async def _capture(self, tab: Tab) -> None:
        try:
            await self._read_frames(tab)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Capture runs independently of browser actions. Deliver its failure
            # to the viewer after releasing Chrome's screencast resources.
            self._fail(tab, error)
        else:
            self._fail(tab, BrowserError("Chrome closed the screencast subscription"))

    async def _read_frames(self, tab: Tab) -> None:
        page = tab.cdp.page
        settings = self._settings
        quality = settings.quality if settings.image_format == "jpeg" else None
        async with tab.cdp.listen(ScreencastFrameEvent, max_queue_size=16) as events:
            try:
                await page.start_screencast(
                    format=settings.image_format,
                    quality=quality,
                    max_width=settings.max_width,
                    max_height=settings.max_height,
                )
                async for event in events:
                    await page.screencast_frame_ack(session_id=event.session_id)
                    self._publish(tab, event)
            finally:
                # A tab or its connection can disappear before stop reaches Chrome.
                with suppress(CDPError):
                    await page.stop_screencast()

    def _publish(self, tab: Tab, event: ScreencastFrameEvent) -> None:
        if self._closed or self._tab is not tab or tab.closed:
            return
        self._latest = ScreencastFrame(
            target_id=tab.id,
            data=event.data,
            mime_type=f"image/{self._settings.image_format}",
            timestamp_seconds=event.metadata.timestamp,
        )
        self._frame_ready.set()

    def _fail(self, tab: Tab, error: Exception) -> None:
        if self._closed or self._tab is not tab or tab.closed:
            return
        self._failure = error
        self._finish()
        self._tab_changed.set()

    def _finish(self) -> None:
        self._closed = True
        self._latest = None
        self._frame_ready.set()


class _State:
    def __init__(self) -> None:
        self.stream: _Stream | None = None
        self.closed = False


class Screencast(Plugin, slot="browserrig.screencast", provides=True):
    """Offer a live Chrome viewport stream to the application's viewer."""

    _browser = needs(Browser)
    _state = PluginState(_State)

    def __init__(
        self,
        *,
        image_format: _ImageFormat = "jpeg",
        quality: int | None = None,
        max_width: int = 1280,
        max_height: int = 800,
    ) -> None:
        super().__init__()
        self._settings = _Settings(
            image_format=image_format,
            quality=quality,
            max_width=max_width,
            max_height=max_height,
        )

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._shutdown)

    @asynccontextmanager
    async def open(self) -> AsyncGenerator[AsyncIterator[ScreencastFrame]]:
        """Follow the active tab until context exit, unmount or session close.

        Use one viewer per session. Iteration keeps only the latest unread frame.
        Chrome failures surface to the viewer when it reads the stream.
        """
        state = self._state
        if state.closed:
            raise BrowserError("Screencast session has closed")
        if state.stream is not None:
            raise BrowserError("A screencast viewer is already open")
        stream = _Stream(self._settings, self._browser.tabs.focused())
        state.stream = stream
        try:
            yield stream.frames()
        finally:
            await stream.close()
            state.stream = None

    @hook(TabActivatedEvent, TabClosedEvent)
    async def _on_tab_changed(self, _event: TabActivatedEvent | TabClosedEvent) -> None:
        if (stream := self._state.stream) is not None:
            stream.follow(self._browser.tabs.focused())

    async def _shutdown(self) -> None:
        self._state.closed = True
        if (stream := self._state.stream) is not None:
            await stream.close()
