import asyncio
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

from .base import EventSink
from .config import BrowserOptions, ConnectBrowser, LaunchBrowser
from .errors import BrowserClosed, BrowserError
from .frames import discover_frames
from .models import Download, DownloadState, TabInfo
from .process import ChromeProcess
from .tab import Frame, Tab, validated_url


async def _discard(_event: BrowserEvent | InputEvent) -> None:
    pass


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
        self._failure: BaseException | None = None
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
            if isinstance(options, LaunchBrowser):
                process = await self._stack.enter_async_context(ChromeProcess(options))
                endpoint, headers = process.endpoint, {}
            else:
                endpoint = options.endpoint.get_secret_value()
                headers = {key: value.get_secret_value() for key, value in options.headers.items()}
            async with asyncio.timeout(options.timeout):
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
                self.client = await self._stack.enter_async_context(
                    CdpClient(
                        endpoint,
                        additional_headers=headers,
                        default_timeout=options.timeout,
                    )
                )
                if not isinstance(options, ConnectBrowser) or options.target_id is None:
                    context = await self.client.target.create_browser_context(
                        dispose_on_detach=True
                    )
                    self._context = context.browser_context_id
                    self._stack.push_async_callback(
                        self.client.target.dispose_browser_context, browser_context_id=self._context
                    )
                    download_directory = (
                        str(self.files.pending_directory)
                        if self.files is not None
                        else options.download_directory
                    )
                    if download_directory is not None:
                        await self.client.browser.set_download_behavior(
                            behavior="allowAndName",
                            download_path=download_directory,
                            browser_context_id=self._context,
                            events_enabled=True,
                        )
                self._start_listeners()
                self._stack.push_async_callback(self._stop_listeners)
                await self.client.target.set_discover_targets(discover=True)
                if isinstance(options, ConnectBrowser) and options.target_id:
                    tab = await self._attach(options.target_id)
                    self._active = tab.id
                    await tab.mouse.initialize_cursor()
                else:
                    await self.open_tab(options.url)
                await self.emit(ConnectedEvent(owned_process=isinstance(options, LaunchBrowser)))
            return self
        except BaseException:
            await self.aclose()
            raise

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

    async def _attach(self, target_id: str) -> Tab:
        async with self._attach_lock:
            if target_id in self._tabs:
                return self._tabs[target_id]
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
                await tab.main_frame()
                self._tabs[target_id] = tab
                self._sessions[attached.session_id] = target_id
                if self._context is None:
                    assert self._stack is not None
                    self._stack.push_async_callback(self._detach, attached.session_id)
                return tab
            except BaseException:
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
        found = []
        for info in result.target_infos:
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
        tab = await self._attach(result.target_id)
        self._active = tab.id
        await self.emit(TabOpenedEvent(target_id=tab.id, url=url))
        await self.emit(TabActivatedEvent(target_id=tab.id, document_id=tab.document_id))
        await tab.mouse.initialize_cursor()
        return tab

    async def activate_tab(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        tab = await self._attach(target_id)
        await tab.cdp.page.bring_to_front()
        self._active = tab.id
        await self.emit(TabActivatedEvent(target_id=tab.id, document_id=tab.document_id))
        await tab.mouse.initialize_cursor()
        return tab

    async def close_tab(self, target_id: str) -> None:
        if target_id not in {tab.id for tab in await self.tabs()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        await self.client.target.close_target(target_id=target_id)
        if tab := self._tabs.get(target_id):
            tab.closed = True
        if self._active == target_id:
            self._active = ""

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
                    match event:
                        case FrameNavigatedEvent(frame=frame) if tab and not frame.parent_id:
                            tab.document_id, tab.url = frame.loader_id, frame.url
                            tab.changed.set()
                            await self.emit(
                                NavigationCommittedEvent(
                                    target_id=tab.id, document_id=tab.document_id, url=tab.url
                                )
                            )
                        case NavigatedWithinDocumentEvent(url=url) if tab:
                            tab.url = url
                            tab.changed.set()
                            await self.emit(
                                NavigationCommittedEvent(
                                    target_id=tab.id, document_id=tab.document_id, url=url
                                )
                            )
                        case JavascriptDialogOpeningEvent(type=kind, message=message) if tab:
                            tab.dialog = (str(kind), message)
                            await self.emit(
                                DialogOpenedEvent(
                                    target_id=tab.id, kind=str(kind), message=message[:1000]
                                )
                            )
                        case JavascriptDialogClosedEvent(result=accepted) if tab:
                            tab.dialog = None
                            await self.emit(DialogHandledEvent(target_id=tab.id, accepted=accepted))
                        case TargetInfoChangedEvent(target_info=info):
                            if known := self._tabs.get(info.target_id):
                                known.url, known.title = info.url, info.title
                            elif (
                                info.type == "page"
                                and self._context
                                and info.browser_context_id == self._context
                            ):
                                await self._attach(info.target_id)
                                await self.emit(
                                    TabOpenedEvent(
                                        target_id=info.target_id,
                                        url=info.url,
                                        opener_id=info.opener_id or "",
                                    )
                                )
                        case TargetDestroyedEvent(target_id=tid) if tid in self._tabs:
                            self._tabs[tid].closed = True
                            await self.emit(TabClosedEvent(target_id=tid))
                        case DownloadWillBeginEvent(guid=guid, url=url, suggested_filename=name):
                            self._downloads[guid] = Download(id=guid, url=url, filename=name)
                            await self.emit(
                                DownloadStartedEvent(download_id=guid, filename=name, url=url)
                            )
                        case DownloadProgressEvent(guid=guid) if guid in self._downloads:
                            await self._download_progress(event)
        except asyncio.CancelledError:
            raise
        except BaseException as error:  # pylint: disable=broad-exception-caught
            # Surface listener failures on the next browser operation.
            self._failure = error

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
                await self.emit(DisconnectedEvent())
