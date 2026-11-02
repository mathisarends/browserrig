from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import TYPE_CHECKING

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

from browserrig.core import BrowserError, TabGesture, TargetId
from browserrig.events import TabActivatedEvent, TabClosedEvent, TabOpenedEvent
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

    async def open(self, target: str | Path = "about:blank") -> Tab:
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
                cdp = self.client.session(sid)
                try:
                    await _enable_session(cdp, self._options, frame=True)
                except (Exception, asyncio.CancelledError):
                    await self._detach(sid)
                    raise
            return self.client.session(sid)

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

    async def _on_target_info(self, info: TargetInfo) -> None:
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


async def _enable_session(
    cdp: CdpSession, options: BrowserOptions, *, frame: bool = False
) -> None:
    """Enable browserrig's domains, then apply the viewport and custom setup."""
    await asyncio.gather(
        cdp.page.enable(),
        cdp.page.set_lifecycle_events_enabled(enabled=True),
        cdp.runtime.enable(),
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
