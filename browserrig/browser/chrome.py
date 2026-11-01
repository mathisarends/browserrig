import asyncio
import logging
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

import httpx2
from cdpify import CdpClient, CdpSession, EventSubscription, ReceivedEvent
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
    TargetInfo,
    TargetInfoChangedEvent,
)

from browserrig.core import BrowserClosed, BrowserError, TabGesture, TargetId
from browserrig.events import (
    ConnectedEvent,
    DisconnectedEvent,
    TabActivatedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)
from browserrig.files import Download, FileSystem, FileSystemOptions
from browserrig.input import Input, Keyboard, Mouse

from .base import BrowserEvents, EventSink, _discard
from .config import BrowserOptions, ConnectBrowser, LaunchBrowser, Viewport
from .downloads import Downloads
from .frame import Frame
from .frames import discover_frames
from .models import TabInfo
from .process import ChromeProcess
from .tab import Tab, validated_url
from .worlds import Worlds

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
        file_system: FileSystemOptions | None = None,
        emit: EventSink = _discard,
    ) -> None:
        self._options = options or LaunchBrowser()
        self.files = (
            FileSystem(file_system, download_directory=self._options.download_directory)
            if isinstance(self._options, LaunchBrowser) or file_system is not None
            else None
        )
        self.id = uuid4().hex
        self.events = BrowserEvents(self.id, emit)
        self._stack: AsyncExitStack | None = None
        self._tabs: dict[TargetId, Tab] = {}
        self._active = ""
        self._context: str | None = None
        self._sessions: dict[str, str] = {}
        self._downloads = Downloads(
            files=self.files,
            directory=self._options.download_directory,
            emit=self.events.emit,
        )
        self._tasks: list[asyncio.Task[None]] = []
        self._failure: Exception | None = None
        self._connected = False
        self._closed_targets: set[TargetId] = set()
        self._worlds = Worlds()
        self._attach_lock = asyncio.Lock()
        self.action_lock = asyncio.Lock()
        # One mouse and keyboard for the whole browser, aimed at the active tab.
        self.input = Input(self._focused)
        self._close_task: asyncio.Task[None] | None = None
        self.client: CdpClient  # smelt: ignore[SMT430] -- raw CDP escape hatch

    async def __aenter__(self) -> Self:
        if self._stack is not None or self._close_task is not None:
            raise BrowserError("A ChromeBrowser instance can be opened only once")
        self._stack = AsyncExitStack()
        try:
            options = self._options
            if self.files is not None:
                await asyncio.to_thread(self.files.initialize)
            async with asyncio.timeout(options.timeout):
                endpoint, headers = await self._resolve_endpoint()
                self.client = await self._stack.enter_async_context(
                    CdpClient(
                        endpoint,
                        additional_headers=headers,
                        default_timeout=options.timeout,
                    )
                )
                await self._create_context()
                self._start_listeners()
                self._stack.push_async_callback(self._stop_listeners)
                await self.client.target.set_discover_targets(discover=True)
                if isinstance(options, ConnectBrowser) and options.target_id:
                    tab = await self._attach(options.target_id)
                    await self.mouse.switch_tab(
                        TabGesture.ACTIVATE,
                        tab.id,
                        lambda: self._focus(tab, front=False),
                    )
                else:
                    await self.open_tab(options.url)
                self._connected = True
                await self.events.emit(
                    ConnectedEvent(owned_process=isinstance(options, LaunchBrowser))
                )
            return self
        except (Exception, asyncio.CancelledError):
            await self.aclose()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def active_tab(self) -> Tab:
        tab = self._focused()
        if tab is None:
            raise BrowserError("No active tab; open or explicitly activate one")
        return tab

    @property
    def mouse(self) -> Mouse:
        return self.input.mouse

    @property
    def keyboard(self) -> Keyboard:
        return self.input.keyboard

    async def tabs(self) -> tuple[TabInfo, ...]:
        self._check()
        targets = await self._targets()
        self._closed_targets.intersection_update(info.target_id for info in targets)
        found = []
        for info in targets:
            if info.target_id in self._closed_targets:
                continue
            if info.type != "page":
                continue
            if self._context is not None and info.browser_context_id != self._context:
                continue
            if self._context is None and info.target_id not in self._tabs:
                continue
            found.append(
                TabInfo(
                    id=info.target_id,
                    title=info.title,
                    url=info.url,
                    active=info.target_id == self._active,
                )
            )
        return tuple(found)

    async def open_tab(self, target: str | Path = "about:blank") -> Tab:
        """Open a URL, or a local file that calling code has already vetted.

        Strings may come from the model and are limited to HTTP(S) and about:blank.
        A `Path` opens as file:// without checks; resolve it through `files` first.
        """
        url = (
            target.absolute().as_uri()
            if isinstance(target, Path)
            else validated_url(target)
        )
        self._check()
        opened: list[Tab] = []

        async def open_new() -> None:
            opened.append(await self._create(url))
            await self._focus(opened[0], front=False)

        await self.mouse.switch_tab(TabGesture.OPEN, "", open_new)
        return opened[0]

    async def activate_tab(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        tab = await self._attach(target_id)
        if tab.id == self._active:
            # Already in front: nothing to press, but late viewers still need the cursor.
            await tab.bring_to_front()
            await self.events.emit(
                TabActivatedEvent(target_id=tab.id, document_id=tab.document_id)
            )
            await self.mouse.publish_cursor()
            return tab
        await self.mouse.switch_tab(
            TabGesture.ACTIVATE, tab.id, lambda: self._focus(tab)
        )
        return tab

    async def close_tab(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")

        async def close() -> None:
            await self.client.target.close_target(target_id=target_id)
            await self._forget(target_id)
            if self._focused() is not None:
                return
            remaining = [tab for tab in await self.tabs() if tab.id != target_id]
            if remaining:
                await self._focus(await self._attach(remaining[0].id))
            else:
                await self._focus(await self._create("about:blank"), front=False)

        await self.mouse.switch_tab(TabGesture.CLOSE, target_id, close)
        return self.active_tab

    async def downloads(self) -> tuple[Download, ...]:
        return self._downloads.all()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(
                self._close(), name="browserrig:close"
            )
        await asyncio.shield(self._close_task)

    async def _resolve_endpoint(self) -> tuple[str, dict[str, str]]:
        assert self._stack is not None
        options = self._options
        if isinstance(options, LaunchBrowser):
            process = await self._stack.enter_async_context(ChromeProcess(options))
            endpoint, headers = process.endpoint, {}
        else:
            endpoint = options.endpoint.get_secret_value()
            headers = {
                key: value.get_secret_value() for key, value in options.headers.items()
            }
        if endpoint.startswith(("http://", "https://")):
            async with httpx2.AsyncClient(
                timeout=options.timeout, headers=headers, trust_env=False
            ) as http:
                response = await http.get(endpoint.rstrip("/") + "/json/version")
                response.raise_for_status()
                endpoint = response.json()["webSocketDebuggerUrl"]
        if "/devtools/page/" in endpoint:
            raise BrowserError(
                "Discovery returned a page endpoint; a browser endpoint is needed"
            )
        return endpoint, headers

    async def _create_context(self) -> None:
        options = self._options
        if isinstance(options, ConnectBrowser) and options.target_id is not None:
            return
        assert self._stack is not None
        context = await self.client.target.create_browser_context(
            dispose_on_detach=True
        )
        self._context = context.browser_context_id
        self._stack.push_async_callback(
            self.client.target.dispose_browser_context, browser_context_id=self._context
        )
        await self._downloads.enable(self.client, self._context)

    def _check(self) -> None:
        if self._stack is None or not self.client.is_connected:
            raise BrowserClosed("Browser connection is closed")
        if self._failure is not None:
            raise BrowserError(
                "Browser event listener failed; reconnect before continuing"
            ) from self._failure

    def _focused(self) -> Tab | None:
        self._check()
        tab = self._tabs.get(self._active)
        return None if tab is None or tab.closed else tab

    async def _create(self, url: str) -> Tab:
        result = await self.client.target.create_target(
            url=url, browser_context_id=self._context
        )
        return await self._attach(result.target_id, opened=True)

    async def _focus(self, tab: Tab, *, front: bool = True) -> None:
        if front:
            await tab.bring_to_front()
        self._active = tab.id
        await self.events.emit(
            TabActivatedEvent(target_id=tab.id, document_id=tab.document_id)
        )

    async def _attach(
        self, target_id: str, *, opened: bool = False, opener_id: str = ""
    ) -> Tab:
        async with self._attach_lock:
            if target_id in self._tabs:
                return self._tabs[target_id]
            if target_id in self._closed_targets:
                raise BrowserError("Target has already closed")
            attached = await self.client.target.attach_to_target(
                target_id=target_id, flatten=True
            )
            cdp = self.client.session(attached.session_id)
            try:
                await _enable_session(cdp, self._options.viewport)
                tab = Tab(
                    target_id,
                    cdp,
                    emit=self.events.emit,
                    worlds=self._worlds,
                    discover_frames=self._discover_frames,
                    current_action=lambda: self.input.action_id,
                )
                await tab.sync_document()
                if target_id in self._closed_targets:
                    raise BrowserError("Target closed while attaching")
                self._tabs[target_id] = tab
                self._sessions[attached.session_id] = target_id
                if opened:
                    await self.events.emit(
                        TabOpenedEvent(
                            target_id=tab.id, url=tab.url, opener_id=opener_id
                        )
                    )
                tab.refresh_strip()
                if self._context is None:
                    assert self._stack is not None
                    self._stack.push_async_callback(self._detach, attached.session_id)
                return tab
            except (Exception, asyncio.CancelledError):
                await self._detach(attached.session_id)
                raise

    async def _detach(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._worlds.invalidate(session_id=session_id)
        if self.client.is_connected:
            # The target may already have been destroyed by its owner.
            with suppress(Exception):
                await self.client.target.detach_from_target(session_id=session_id)

    async def _forget(self, target_id: str) -> None:
        self._closed_targets.add(target_id)
        tab = self._tabs.pop(target_id, None)
        for sid, tid in tuple(self._sessions.items()):
            if tid == target_id:
                self._sessions.pop(sid, None)
                self._worlds.invalidate(session_id=sid)
        if self._active == target_id:
            self._active = ""
        self.mouse.forget(target_id)
        if tab is not None:
            tab.discard()
            await self.events.emit(TabClosedEvent(target_id=target_id))

    async def _discover_frames(
        self, tab: Tab
    ) -> tuple[tuple[Frame, ...], tuple[str, ...]]:
        """Resolve each frame to its own session, including cross-process targets."""
        self._check()
        targets = await self._targets()
        live = {info.target_id for info in targets if info.type == "iframe"}
        for sid, target_id in tuple(self._sessions.items()):
            if target_id not in self._tabs and target_id not in live:
                await self._detach(sid)
        return await discover_frames(tab, targets, self._frame_session)

    async def _targets(self) -> tuple[TargetInfo, ...]:
        result = await self.client.target.get_targets()
        return tuple(result.target_infos)

    async def _frame_session(self, frame_id: str) -> CdpSession:
        """Reuse owned OOPIF sessions; discard stale sessions when targets disappear."""
        async with self._attach_lock:
            sid = next(
                (sid for sid, tid in self._sessions.items() if tid == frame_id), None
            )
            if sid is None:
                attached = await self.client.target.attach_to_target(
                    target_id=frame_id, flatten=True
                )
                sid = attached.session_id
                self._sessions[sid] = frame_id
                assert self._stack is not None
                self._stack.push_async_callback(self._detach, sid)
                await _enable_session(self.client.session(sid))
            return self.client.session(sid)

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
        if session_id is None:
            match event:
                case TargetInfoChangedEvent(target_info=info):
                    await self._on_target_info(info)
                case TargetDestroyedEvent(target_id=target_id):
                    await self._forget(target_id)
                case DownloadWillBeginEvent() | DownloadProgressEvent():
                    await self._downloads.handle(event)
            return
        self._invalidate_contexts(event, session_id)
        if tab := self._tabs.get(self._sessions.get(session_id, "")):
            await tab.handle(event)

    def _invalidate_contexts(self, event: Any, session_id: str) -> None:
        match event:
            case ExecutionContextsClearedEvent():
                self._worlds.invalidate(session_id=session_id)
            case ExecutionContextDestroyedEvent(execution_context_id=context):
                self._worlds.invalidate(session_id=session_id, context_id=context)
            case FrameNavigatedEvent(frame=frame):
                self._worlds.invalidate(frame_id=frame.id)
                for tab in self._tabs.values():
                    tab.layout_changed()

    async def _on_target_info(self, info: TargetInfo) -> None:
        if known := self._tabs.get(info.target_id):
            known.url, known.title = info.url, info.title
            await known.publish_state()
        elif (
            info.type == "page"
            and self._context
            and info.browser_context_id == self._context
        ):
            await self._attach(
                info.target_id, opened=True, opener_id=info.opener_id or ""
            )

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
                for tab in self._tabs.values():
                    tab.discard()
                if self._connected:
                    self._connected = False
                    await self.events.emit(DisconnectedEvent())


async def _enable_session(cdp: CdpSession, viewport: Viewport | None = None) -> None:
    """Enable the domains browserrig listens to, plus optional viewport emulation."""
    steps = [
        cdp.page.enable(),
        cdp.page.set_lifecycle_events_enabled(enabled=True),
        cdp.runtime.enable(),
    ]
    if viewport:
        steps.append(
            cdp.emulation.set_device_metrics_override(
                width=viewport.width,
                height=viewport.height,
                device_scale_factor=viewport.scale,
                mobile=False,
            )
        )
    await asyncio.gather(*steps)
