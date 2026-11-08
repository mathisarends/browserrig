import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any, Self
from uuid import uuid4

import httpx2
from cdpify import CdpClient, EventSubscription, ReceivedEvent
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent
from cdpify.domains.page import (
    FrameNavigatedEvent,
    FrameStartedLoadingEvent,
    FrameStartedNavigatingEvent,
    FrameStoppedLoadingEvent,
    JavascriptDialogClosedEvent,
    JavascriptDialogOpeningEvent,
    LifecycleEventEvent,
    NavigatedWithinDocumentEvent,
)
from cdpify.domains.runtime import (
    ExecutionContextDestroyedEvent,
    ExecutionContextsClearedEvent,
)
from cdpify.domains.target import (
    TargetDestroyedEvent,
    TargetInfoChangedEvent,
)

from browserrig.core import BrowserClosed, BrowserError
from browserrig.events import (
    ConnectedEvent,
    DisconnectedEvent,
)
from browserrig.files import Download, FileBridge, FileTransfer
from browserrig.input import Input, InputTarget, Keyboard, Mouse

from .base import BrowserEvents, EventSink, _discard
from .config import BrowserOptions, CdpEndpoint, Launch
from .downloads import Downloads
from .tab import Tab, TabListener
from .tabs import Tabs

logger = logging.getLogger(__name__)

# Page and runtime events arrive on tab sessions; target and download events on the root.
_EVENTS = (
    FrameNavigatedEvent,
    NavigatedWithinDocumentEvent,
    FrameStartedLoadingEvent,
    FrameStartedNavigatingEvent,
    LifecycleEventEvent,
    FrameStoppedLoadingEvent,
    JavascriptDialogOpeningEvent,
    JavascriptDialogClosedEvent,
    ExecutionContextDestroyedEvent,
    ExecutionContextsClearedEvent,
    TargetInfoChangedEvent,
    TargetDestroyedEvent,
    DownloadWillBeginEvent,
    DownloadProgressEvent,
)


class ChromeBrowser:
    def __init__(
        self,
        options: BrowserOptions | None = None,
        *,
        emit: EventSink = _discard,
        on_tab_change: TabListener | None = None,
    ) -> None:
        self._options = options if options is not None else Launch()
        self.bridge: FileBridge | None = self._options.bridge
        self.id = uuid4().hex
        self.events = BrowserEvents(self.id, emit)
        self._stack: AsyncExitStack | None = None
        self._downloads = Downloads(emit=self.events.emit)
        self._context: str | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._failure: Exception | None = None
        self._connected = False
        self.action_lock = asyncio.Lock()
        # One mouse and keyboard for the whole browser, aimed at the active tab.
        self.input = Input(self._focused_input)
        self.tabs = Tabs(
            self._options,
            self.input,
            check=self._check,
            emit=self.events.emit,
            on_change=on_tab_change,
        )
        self._close_task: asyncio.Task[None] | None = None
        self.client: CdpClient

    async def __aenter__(self) -> Self:
        if self._stack is not None or self._close_task is not None:
            raise BrowserError("A ChromeBrowser instance can be opened only once")
        self._stack = AsyncExitStack()
        try:
            options = self._options
            async with asyncio.timeout(options.timeout):
                endpoint = await self._resolve_endpoint()
                self.client = await self._stack.enter_async_context(
                    CdpClient(
                        endpoint.url,
                        additional_headers=endpoint.headers,
                        default_timeout=options.timeout,
                    )
                )
                self._context = await self.tabs.start(self.client, self._stack)
                self._start_listeners()
                self._stack.push_async_callback(self._stop_listeners)
                await self.client.target.set_discover_targets(discover=True)
                await self.tabs.open_initial()
                self._connected = True
                await self.events.emit(
                    ConnectedEvent(owned_process=options.owns_process)
                )
            return self
        except (Exception, asyncio.CancelledError):
            await self.aclose()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def active_tab(self) -> Tab:
        return self.tabs.active

    @property
    def mouse(self) -> Mouse:
        return self.input.mouse

    @property
    def keyboard(self) -> Keyboard:
        return self.input.keyboard

    async def downloads(self) -> tuple[Download, ...]:
        return self._downloads.all()

    async def receive_downloads(self, transfer: FileTransfer | None) -> bool:
        """Save later downloads into the workspace through `transfer`; `None` stops.

        Returns whether downloads are received. An attached tab keeps its browser's
        download policy, so its downloads are tracked only.
        """
        self._check()
        return await self._downloads.receive(self.client, self._context, transfer)

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(), name="browserrig:close"
            )
        await asyncio.shield(self._close_task)

    async def _resolve_endpoint(self) -> CdpEndpoint:
        """Resolve an HTTP discovery endpoint to the browser's WebSocket."""
        assert self._stack is not None
        options = self._options
        endpoint = await options.cdp_endpoint(self._stack)
        url = endpoint.url
        if url.startswith(("http://", "https://")):
            async with httpx2.AsyncClient(
                timeout=options.timeout, headers=endpoint.headers, trust_env=False
            ) as http:
                response = await http.get(url.rstrip("/") + "/json/version")
                response.raise_for_status()
                url = response.json()["webSocketDebuggerUrl"]
        if "/devtools/page/" in url:
            raise BrowserError(
                "Discovery returned a page endpoint; a browser endpoint is needed"
            )
        return CdpEndpoint(url=url, headers=endpoint.headers)

    def _check(self) -> None:
        if self._stack is None or not self.client.is_connected:
            raise BrowserClosed("Browser connection is closed")
        if self._failure is not None:
            raise BrowserError(
                "Browser event listener failed; reconnect before continuing"
            ) from self._failure

    def _focused_input(self) -> InputTarget | None:
        tab = self.tabs.focused()
        return None if tab is None else tab.input

    def _start_listeners(self) -> None:
        for event_type in _EVENTS:
            subscription = self.client.listen_all(event_type)
            self._tasks.append(
                asyncio.create_task(
                    self._consume(subscription),
                    name=f"browserrig:{event_type.__name__}",
                )
            )

    async def _consume(
        self, subscription: EventSubscription[ReceivedEvent[Any]]
    ) -> None:
        try:
            async with subscription:
                async for received in subscription:
                    try:
                        await self._handle(received.value, received.session_id)
                    except Exception:  # pylint: disable=broad-exception-caught
                        # A target can disappear while its event is being handled.
                        logger.exception(
                            "Browser event %s failed", type(received.value).__name__
                        )
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Surface listener failures on the next browser operation.
            self._failure = error

    async def _handle(self, event: Any, session_id: str | None) -> None:
        if session_id is None and isinstance(
            event, (DownloadWillBeginEvent, DownloadProgressEvent)
        ):
            await self._downloads.handle(event)
        else:
            await self.tabs.handle(event, session_id)

    async def _stop_listeners(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _close(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            try:
                await stack.aclose()
            finally:
                await self.tabs.discard()
                if self._connected:
                    self._connected = False
                    await self.events.emit(DisconnectedEvent())
