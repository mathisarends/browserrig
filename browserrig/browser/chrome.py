import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import replace
from typing import Any, Self
from uuid import uuid4

import httpx2
from cdpify import CdpClient, CdpSession
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent
from cdpify.domains.page import (
    FrameNavigatedEvent,
    JavascriptDialogClosedEvent,
    JavascriptDialogOpeningEvent,
    NavigatedWithinDocumentEvent,
)
from cdpify.domains.target import TargetDestroyedEvent, TargetInfoChangedEvent

from browserrig.browser.models import TabInfo
from browserrig.core.errors import BrowserClosed, BrowserError
from browserrig.events import (
    BrowserEvent,
    ConnectedEvent,
    DialogHandledEvent,
    DialogOpenedEvent,
    DisconnectedEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadStartedEvent,
    InputEvent,
    NavigationCommittedEvent,
    TabActivatedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)
from browserrig.files import FileSystem, FileSystemOptions
from browserrig.files.models import Download, DownloadState

from .base import EventSink
from .config import BrowserOptions, ConnectBrowser, LaunchBrowser
from .frames import discover_frames
from .process import ChromeProcess
from .tab import Frame, Tab, validated_url


async def _discard(_event: BrowserEvent | InputEvent) -> None:
    pass


logger = logging.getLogger(__name__)


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
        self._emit = emit
        self._stack: AsyncExitStack | None = None
        self._tabs: dict[str, Tab] = {}
        self._active = ""
        self._context: str | None = None
        self._sessions: dict[str, str] = {}
        self._downloads: dict[str, Download] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._failure: Exception | None = None
        self._connected = False
        self._closed_targets: set[str] = set()
        self._attach_lock = asyncio.Lock()
        self.action_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self.client: CdpClient

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
                    self._active = tab.id
                    await tab.mouse.initialize_cursor()
                else:
                    await self.open_tab(options.url)
                self._connected = True
                await self.emit(ConnectedEvent(owned_process=isinstance(options, LaunchBrowser)))
            return self
        except (Exception, asyncio.CancelledError):
            await self.aclose()
            raise

    async def _resolve_endpoint(self) -> tuple[str, dict[str, str]]:
        assert self._stack is not None
        options = self._options
        if isinstance(options, LaunchBrowser):
            process = await self._stack.enter_async_context(ChromeProcess(options))
            endpoint, headers = process.endpoint, {}
        else:
            endpoint = options.endpoint.get_secret_value()
            headers = {key: value.get_secret_value() for key, value in options.headers.items()}
        if endpoint.startswith(("http://", "https://")):
            async with httpx2.AsyncClient(
                timeout=options.timeout, headers=headers, trust_env=False
            ) as http:
                response = await http.get(endpoint.rstrip("/") + "/json/version")
                response.raise_for_status()
                endpoint = response.json()["webSocketDebuggerUrl"]
        if "/devtools/page/" in endpoint:
            raise BrowserError("Discovery returned a page endpoint; a browser endpoint is needed")
        return endpoint, headers

    async def _create_context(self) -> None:
        options = self._options
        if isinstance(options, ConnectBrowser) and options.target_id is not None:
            return
        assert self._stack is not None
        context = await self.client.target.create_browser_context(dispose_on_detach=True)
        self._context = context.browser_context_id
        self._stack.push_async_callback(
            self.client.target.dispose_browser_context, browser_context_id=self._context
        )
        await self._configure_downloads()

    async def _configure_downloads(self) -> None:
        directory = (
            str(self.files.pending_directory) if self.files else self._options.download_directory
        )
        if directory is not None:
            await self.client.browser.set_download_behavior(
                behavior="allowAndName",
                download_path=directory,
                browser_context_id=self._context,
                events_enabled=True,
            )

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    @property
    def active_tab(self) -> Tab:
        self._check()
        tab = self._tabs.get(self._active)
        if tab is None or tab.closed:
            raise BrowserError("No active tab; open or explicitly activate one")
        return tab

    def _check(self) -> None:
        if self._stack is None or not self.client.is_connected:
            raise BrowserClosed("Browser connection is closed")
        if self._failure is not None:
            raise BrowserError(
                "Browser event listener failed; reconnect before continuing"
            ) from self._failure

    async def emit(self, event: BrowserEvent | InputEvent) -> None:
        await self._emit(replace(event, browser_id=self.id))

    async def _attach(self, target_id: str, *, opened: bool = False, opener_id: str = "") -> Tab:
        async with self._attach_lock:
            if target_id in self._tabs:
                return self._tabs[target_id]
            if target_id in self._closed_targets:
                raise BrowserError("Target has already closed")
            attached = await self.client.target.attach_to_target(target_id=target_id, flatten=True)
            cdp = self.client.session(attached.session_id)
            try:
                await cdp.page.enable()
                await cdp.runtime.enable()
                options = self._options
                if options.viewport:
                    size = options.viewport
                    await cdp.emulation.set_device_metrics_override(
                        width=size.width,
                        height=size.height,
                        device_scale_factor=size.scale,
                        mobile=False,
                    )
                tab = Tab(target_id, cdp, emit=self.emit)
                await tab.sync_document()
                if target_id in self._closed_targets:
                    raise BrowserError("Target closed while attaching")
                self._tabs[target_id] = tab
                self._sessions[attached.session_id] = target_id
                if opened:
                    await self.emit(
                        TabOpenedEvent(target_id=tab.id, url=tab.url, opener_id=opener_id)
                    )
                if self._context is None:
                    assert self._stack is not None
                    self._stack.push_async_callback(self._detach, attached.session_id)
                return tab
            except (Exception, asyncio.CancelledError):
                await self._detach(attached.session_id)
                raise

    async def _detach(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self.client.is_connected:
            # The target may already have been destroyed by its owner.
            with suppress(Exception):
                await self.client.target.detach_from_target(session_id=session_id)

    async def tabs(self) -> tuple[TabInfo, ...]:
        self._check()
        result = await self.client.target.get_targets()
        self._closed_targets.intersection_update(info.target_id for info in result.target_infos)
        found = []
        for info in result.target_infos:
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

    async def open_tab(self, url: str = "about:blank") -> Tab:
        return await self._open_tab(validated_url(url))

    async def open_file(self, path: str) -> Tab:
        if self.files is None:
            raise BrowserError("A shared local file system must be configured for this browser")
        resolved = self.files.resolve(path)
        if not await asyncio.to_thread(resolved.is_file):
            raise BrowserError(f"File not found: {path}")
        return await self._open_tab(resolved.as_uri())

    async def _open_tab(self, url: str) -> Tab:
        self._check()
        result = await self.client.target.create_target(url=url, browser_context_id=self._context)
        tab = await self._attach(result.target_id, opened=True)
        self._active = tab.id
        await self.emit(TabActivatedEvent(target_id=tab.id, document_id=tab.document_id))
        await tab.mouse.initialize_cursor()
        return tab

    async def activate_tab(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        tab = await self._attach(target_id)
        await tab.bring_to_front()
        self._active = tab.id
        await self.emit(TabActivatedEvent(target_id=tab.id, document_id=tab.document_id))
        await tab.mouse.initialize_cursor()
        return tab

    async def close_tab(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        await self.client.target.close_target(target_id=target_id)
        await self._forget(target_id)
        if self._active and self._active in self._tabs:
            return self.active_tab
        remaining = [tab for tab in await self.tabs() if tab.id != target_id]
        return await self.activate_tab(remaining[0].id) if remaining else await self.open_tab()

    async def _forget(self, target_id: str) -> None:
        self._closed_targets.add(target_id)
        tab = self._tabs.pop(target_id, None)
        for sid, tid in tuple(self._sessions.items()):
            if tid == target_id:
                self._sessions.pop(sid, None)
        if self._active == target_id:
            self._active = ""
        if tab is not None:
            tab.closed = True
            await self.emit(TabClosedEvent(target_id=target_id))

    async def frames(self, tab: Tab) -> tuple[Frame, ...]:
        """Resolve each frame to its own session, including cross-process targets."""
        self._check()
        targets = tuple((await self.client.target.get_targets()).target_infos)
        live = {info.target_id for info in targets if info.type == "iframe"}
        for sid, target_id in tuple(self._sessions.items()):
            if target_id not in self._tabs and target_id not in live:
                await self._detach(sid)
        return await discover_frames(tab, targets, self._frame_session)

    async def _frame_session(self, frame_id: str) -> CdpSession:
        """Reuse owned OOPIF sessions; discard stale sessions when targets disappear."""
        async with self._attach_lock:
            sid = next((sid for sid, tid in self._sessions.items() if tid == frame_id), None)
            if sid is None:
                attached = await self.client.target.attach_to_target(
                    target_id=frame_id, flatten=True
                )
                sid = attached.session_id
                self._sessions[sid] = frame_id
                assert self._stack is not None
                self._stack.push_async_callback(self._detach, sid)
            return self.client.session(sid)

    async def downloads(self) -> tuple[Download, ...]:
        return tuple(self._downloads.values())

    async def publish_cursor(self) -> None:
        await self.active_tab.mouse.publish_cursor()

    def _start_listeners(self) -> None:
        for event_type in (
            FrameNavigatedEvent,
            NavigatedWithinDocumentEvent,
            JavascriptDialogOpeningEvent,
            JavascriptDialogClosedEvent,
        ):
            subscription = self.client.listen_all(event_type)
            self._tasks.append(
                asyncio.create_task(
                    self._consume(subscription, True), name=f"browserrig:{event_type.__name__}"
                )
            )
        for event_type in (
            TargetInfoChangedEvent,
            TargetDestroyedEvent,
            DownloadWillBeginEvent,
            DownloadProgressEvent,
        ):
            subscription = self.client.listen(event_type)
            self._tasks.append(
                asyncio.create_task(
                    self._consume(subscription, False), name=f"browserrig:{event_type.__name__}"
                )
            )

    async def _consume(self, subscription: Any, scoped: bool) -> None:
        try:
            async with subscription:
                async for received in subscription:
                    event = received.value if scoped else received
                    target_id = self._sessions.get(received.session_id, "") if scoped else ""
                    tab = self._tabs.get(target_id)
                    try:
                        await self._dispatch(event, tab)
                    except Exception:  # pylint: disable=broad-exception-caught
                        # A target can disappear while its event is being handled.
                        logger.exception("Browser event %s failed", type(event).__name__)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Surface listener failures on the next browser operation.
            self._failure = error

    async def _dispatch(self, event: Any, tab: Tab | None) -> None:
        handlers: dict[type, Callable[[Any, Tab | None], Awaitable[None]]] = {
            FrameNavigatedEvent: self._on_frame_navigated,
            NavigatedWithinDocumentEvent: self._on_within_document,
            JavascriptDialogOpeningEvent: self._on_dialog_opened,
            JavascriptDialogClosedEvent: self._on_dialog_closed,
            TargetInfoChangedEvent: self._on_target_info,
            TargetDestroyedEvent: self._on_target_destroyed,
            DownloadWillBeginEvent: self._on_download_started,
            DownloadProgressEvent: self._on_download_progress,
        }
        if handler := handlers.get(type(event)):
            await handler(event, tab)

    async def _on_frame_navigated(self, event: FrameNavigatedEvent, tab: Tab | None) -> None:
        if tab is not None and not event.frame.parent_id:
            tab.document_id, tab.url = event.frame.loader_id, event.frame.url
            tab.changed.set()
            await self.emit(
                NavigationCommittedEvent(target_id=tab.id, document_id=tab.document_id, url=tab.url)
            )

    async def _on_within_document(
        self, event: NavigatedWithinDocumentEvent, tab: Tab | None
    ) -> None:
        if tab is not None:
            tab.url = event.url
            tab.changed.set()
            await self.emit(
                NavigationCommittedEvent(target_id=tab.id, document_id=tab.document_id, url=tab.url)
            )

    async def _on_dialog_opened(self, event: JavascriptDialogOpeningEvent, tab: Tab | None) -> None:
        if tab is not None:
            tab.dialog = (str(event.type), event.message)
            await self.emit(
                DialogOpenedEvent(
                    target_id=tab.id, kind=str(event.type), message=event.message[:1000]
                )
            )

    async def _on_dialog_closed(self, event: JavascriptDialogClosedEvent, tab: Tab | None) -> None:
        if tab is not None:
            tab.dialog = None
            await self.emit(DialogHandledEvent(target_id=tab.id, accepted=event.result))

    async def _on_target_info(self, event: TargetInfoChangedEvent, _tab: Tab | None) -> None:
        info = event.target_info
        if known := self._tabs.get(info.target_id):
            known.url, known.title = info.url, info.title
        elif info.type == "page" and self._context and info.browser_context_id == self._context:
            await self._attach(info.target_id, opened=True, opener_id=info.opener_id or "")

    async def _on_target_destroyed(self, event: TargetDestroyedEvent, _tab: Tab | None) -> None:
        await self._forget(event.target_id)

    async def _on_download_started(self, event: DownloadWillBeginEvent, _tab: Tab | None) -> None:
        self._downloads[event.guid] = Download(
            id=event.guid, url=event.url, filename=event.suggested_filename
        )
        await self.emit(
            DownloadStartedEvent(
                download_id=event.guid, filename=event.suggested_filename, url=event.url
            )
        )

    async def _on_download_progress(self, event: DownloadProgressEvent, _tab: Tab | None) -> None:
        if event.guid in self._downloads:
            await self._download_progress(event)

    async def _download_progress(self, event: DownloadProgressEvent) -> None:
        guid = event.guid
        previous = self._downloads[guid]
        # Terminal CDP events can be repeated; never move an already completed file twice.
        if previous.state != DownloadState.IN_PROGRESS:
            return
        path, error = event.file_path, None
        if event.state == DownloadState.COMPLETED and self.files is not None:
            try:
                path = await asyncio.to_thread(
                    self.files.complete_download, guid, previous.filename, path
                )
            except (OSError, ValueError) as failure:
                # A single missing file must not stop browser event processing.
                path, error = None, f"Downloaded file could not be saved: {failure}"
        download = Download(
            id=guid,
            url=previous.url,
            filename=previous.filename,
            state=DownloadState(event.state),
            received_bytes=int(event.received_bytes),
            path=path,
            error=error,
        )
        self._downloads[guid] = download
        match download.state:
            case DownloadState.COMPLETED:
                if error is not None:
                    await self.emit(DownloadFailedEvent(download_id=guid, reason=error))
                    return
                await self.emit(
                    DownloadCompletedEvent(
                        download_id=guid,
                        filename=download.filename,
                        size=download.received_bytes,
                    )
                )
            case DownloadState.CANCELED:
                await self.emit(
                    DownloadFailedEvent(download_id=guid, reason="Download canceled by browser")
                )

    async def _stop_listeners(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def aclose(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="browserrig:close")
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            try:
                await stack.aclose()
            finally:
                for tab in self._tabs.values():
                    tab.closed = True
                if self._connected:
                    self._connected = False
                    await self.emit(DisconnectedEvent())
