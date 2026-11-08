from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from pathlib import Path, PurePath, PureWindowsPath
from typing import TYPE_CHECKING
from urllib.parse import quote

from cdpify import CdpClient, CdpSession
from cdpify.domains.page import FrameNavigatedEvent
from cdpify.domains.runtime import (
    ExecutionContextDestroyedEvent,
    ExecutionContextsClearedEvent,
)
from cdpify.domains.target import (
    TargetDestroyedEvent,
    TargetInfo,
    TargetInfoChangedEvent,
)
from harnessed.tracing import traced

from browserrig.core import BrowserError, TabGesture, TargetId
from browserrig.events import (
    TabActivatedEvent,
    TabClosedEvent,
    TabClosingEvent,
    TabOpenedEvent,
)
from browserrig.input import Input

from .config import BrowserOptions
from .frame import Frame
from .frames import discover_frames
from .models import TabInfo
from .tab import Tab, TabListener, validated_url
from .worlds import Worlds

if TYPE_CHECKING:
    from .base import EventSink


class Tabs:
    """The browser's controlled tabs, their sessions and active document."""

    def __init__(
        self,
        options: BrowserOptions,
        devices: Input,
        *,
        check: Callable[[], None],
        emit: EventSink,
        on_change: TabListener | None = None,
    ) -> None:
        self._options = options
        self._input = devices
        self._check = check
        self._emit = emit
        self._on_tab_change = on_change
        self._tabs: dict[TargetId, Tab] = {}
        self._active = ""
        self._context: str | None = None
        self._target_context: str | None = None
        self._sessions: dict[str, str] = {}
        self._closed_targets: set[TargetId] = set()
        # Every tab opened in this session, oldest first, and a signal for the next one.
        self._opened: list[TargetId] = []
        self._opening = asyncio.Event()
        self._link_modifier = ""
        self._worlds = Worlds()
        self._attach_lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self.client: CdpClient

    @property
    def active(self) -> Tab:
        tab = self.focused()
        if tab is None:
            raise BrowserError("No active tab; open or explicitly activate one")
        return tab

    async def start(self, client: CdpClient, stack: AsyncExitStack) -> str | None:
        """Bind the connection and create its controlled browser context."""
        self.client = client
        self._stack = stack
        await self._create_context()
        return self._context

    async def open_initial(self) -> None:
        if self._options.target_id is None:
            await self.open(self._options.url)
            return
        tab = await self._attach(self._options.target_id)
        await self._input.mouse.switch_tab(
            TabGesture.ACTIVATE, tab.id, lambda: self._focus(tab, front=False)
        )

    async def discard(self) -> None:
        for tab in tuple(self._tabs.values()):
            await tab.discard()

    @traced
    async def list(self) -> tuple[TabInfo, ...]:
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

    async def open(self, target: str | PurePath = "about:blank") -> Tab:
        """Open a URL, or a file on the browser host that calling code has vetted.

        Strings may come from the model and are limited to HTTP(S) and about:blank.
        A path opens as file:// without checks; get it from `FileTransfer.stage` first.
        """
        if isinstance(target, Path):
            url = target.absolute().as_uri()
        elif isinstance(target, PurePath):
            url = file_url(target)
        else:
            url = validated_url(target)
        self._check()
        opened: list[Tab] = []

        async def open_new() -> None:
            opened.append(await self._create(url))
            await self._focus(opened[0], front=False)

        await self._input.mouse.switch_tab(TabGesture.OPEN, "", open_new)
        return opened[0]

    async def activate(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.list()}:
            raise BrowserError("Target is outside this browser's controlled scope")
        tab = await self._attach(target_id)
        if tab.id == self._active:
            # Already in front: nothing to press, but late viewers still need the cursor.
            await tab.bring_to_front()
            await self._emit(
                TabActivatedEvent(target_id=tab.id, document_id=tab.document_id)
            )
            await self._input.mouse.publish_cursor()
            return tab
        await self._input.mouse.switch_tab(
            TabGesture.ACTIVATE, tab.id, lambda: self._focus(tab)
        )
        return tab

    async def close(self, target_id: str) -> Tab:
        if target_id not in {tab.id for tab in await self.list()}:
            raise BrowserError("Target is outside this browser's controlled scope")

        async def close() -> None:
            await self._emit(TabClosingEvent(target_id=target_id))
            await self.client.target.close_target(target_id=target_id)
            await self._forget(target_id)
            if self.focused() is not None:
                return
            remaining = [tab for tab in await self.list() if tab.id != target_id]
            if remaining:
                await self._focus(await self._attach(remaining[0].id))
            else:
                await self._focus(await self._create("about:blank"), front=False)

        await self._input.mouse.switch_tab(TabGesture.CLOSE, target_id, close)
        return self.active

    @property
    def openings(self) -> int:
        """How many tabs have opened so far; a mark to pass to `opened_since`."""
        return len(self._opened)

    async def opened_since(self, mark: int, *, timeout: float = 0) -> Tab | None:
        """The newest open tab opened after `mark`, waiting up to `timeout` for one."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            for target_id in reversed(self._opened[mark:]):
                tab = self._tabs.get(target_id)
                if tab is not None and not tab.closed:
                    return tab
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            with suppress(TimeoutError):
                async with asyncio.timeout(remaining):
                    await self._opening.wait()

    async def link_modifier(self) -> str:
        """The key held while clicking a link to open it in a new tab on the browser's host."""
        if not self._link_modifier:
            self._check()
            version = await self.client.browser.get_version()
            self._link_modifier = (
                "Meta" if "Macintosh" in version.user_agent else "Control"
            )
        return self._link_modifier

    def focused(self) -> Tab | None:
        self._check()
        tab = self._tabs.get(self._active)
        return None if tab is None or tab.closed else tab

    async def handle(self, event: object, session_id: str | None) -> None:
        if session_id is None:
            match event:
                case TargetInfoChangedEvent(target_info=info):
                    await self._on_target_info(info)
                case TargetDestroyedEvent(target_id=target_id):
                    await self._forget(target_id)
            return
        self._invalidate_contexts(event, session_id)
        if tab := self._tabs.get(self._sessions.get(session_id, "")):
            await tab.handle(event)

    async def _create_context(self) -> None:
        options = self._options
        if options.target_id is not None:
            target = await self.client.target.get_target_info(
                target_id=options.target_id
            )
            self._target_context = target.target_info.browser_context_id
            return
        assert self._stack is not None
        context = await self.client.target.create_browser_context(
            dispose_on_detach=True
        )
        self._context = context.browser_context_id
        self._stack.push_async_callback(
            self.client.target.dispose_browser_context, browser_context_id=self._context
        )

    async def _create(self, url: str) -> Tab:
        result = await self.client.target.create_target(
            url=url, browser_context_id=self._context or self._target_context
        )
        return await self._attach(result.target_id, opened=True)

    async def _focus(self, tab: Tab, *, front: bool = True) -> None:
        if front:
            await tab.bring_to_front()
        self._active = tab.id
        await self._emit(
            TabActivatedEvent(target_id=tab.id, document_id=tab.document_id)
        )

    async def _on_target_info(self, info: TargetInfo) -> None:
        if info.target_id in self._closed_targets:
            return
        if known := self._tabs.get(info.target_id):
            known.url, known.title = info.url, info.title
            await known.report_change()
        elif (
            info.type == "page"
            and self._context
            and info.browser_context_id == self._context
        ):
            await self._attach(
                info.target_id, opened=True, opener_id=info.opener_id or ""
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
                await _enable_session(cdp, self._options)
                tab = Tab(
                    target_id,
                    cdp,
                    emit=self._emit,
                    worlds=self._worlds,
                    discover_frames=self._discover_frames,
                    current_action=lambda: self._input.action_id,
                    on_change=self._on_tab_change,
                )
                await tab.sync_document()
                if target_id in self._closed_targets:
                    raise BrowserError("Target closed while attaching")
                self._tabs[target_id] = tab
                self._sessions[attached.session_id] = target_id
                if opened:
                    self._opened.append(target_id)
                    self._opening.set()
                    self._opening = asyncio.Event()
                    await self._emit(
                        TabOpenedEvent(
                            target_id=tab.id, url=tab.url, opener_id=opener_id
                        )
                    )
                # A tab attached mid-session already shows a page worth reading.
                await tab.report_change(settled=True)
                if self._context is None:
                    assert self._stack is not None
                    self._stack.push_async_callback(self._detach, attached.session_id)
                return tab
            except (Exception, asyncio.CancelledError):
                await self._detach(attached.session_id)
                raise

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
                cdp = self.client.session(sid)
                try:
                    await _enable_session(cdp, self._options, frame=True)
                except (Exception, asyncio.CancelledError):
                    await self._detach(sid)
                    raise
            return self.client.session(sid)

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
        self._input.mouse.forget(target_id)
        if tab is not None:
            await tab.discard()
            await self._emit(TabClosedEvent(target_id=target_id))

    async def _targets(self) -> tuple[TargetInfo, ...]:
        result = await self.client.target.get_targets()
        return tuple(result.target_infos)

    def _invalidate_contexts(self, event: object, session_id: str) -> None:
        match event:
            case ExecutionContextsClearedEvent():
                self._worlds.invalidate(session_id=session_id)
            case ExecutionContextDestroyedEvent(execution_context_id=context):
                self._worlds.invalidate(session_id=session_id, context_id=context)
            case FrameNavigatedEvent(frame=frame):
                self._worlds.invalidate(frame_id=frame.id)
                for tab in self._tabs.values():
                    tab.layout_changed()


def file_url(path: PurePath) -> str:  # smelt: ignore[SMT429] -- pure, table-tested
    """A file:// URL for a path on the browser host, whose OS may differ from ours."""
    if not path.is_absolute():
        raise ValueError("A browser host path must be absolute")
    posix = path.as_posix()
    if isinstance(path, PureWindowsPath):
        if path.drive.endswith(":"):
            rest = posix[len(path.drive) :].lstrip("/")
            return f"file:///{path.drive}/{quote(rest)}"
        return "file:" + quote(posix)
    return "file://" + quote(posix)


async def _enable_session(
    cdp: CdpSession, options: BrowserOptions, *, frame: bool = False
) -> None:
    """Enable browserrig's domains, then apply the viewport and custom setup."""
    await asyncio.gather(
        cdp.page.enable(),
        cdp.page.set_lifecycle_events_enabled(enabled=True),
        cdp.runtime.enable(),
        # Readiness only needs request timing; Chrome keeps no bodies for us.
        *(
            ()
            if frame
            else (
                cdp.network.enable(
                    max_total_buffer_size=0,
                    max_resource_buffer_size=0,
                    max_post_data_size=0,
                ),
            )
        ),
    )
    viewport = options.viewport
    if viewport is not None and not frame:
        await cdp.emulation.set_device_metrics_override(
            width=viewport.width,
            height=viewport.height,
            device_scale_factor=viewport.scale,
            mobile=False,
        )
    for setup in options.session_setup:
        await setup.apply(cdp, frame=frame)
