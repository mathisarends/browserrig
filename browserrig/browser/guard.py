from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from typing import TYPE_CHECKING, Any

from cdpify import CdpClient, CDPCommandError, EventSubscription, ReceivedEvent
from cdpify.domains.fetch import RequestPattern, RequestPausedEvent
from cdpify.domains.network import ErrorReason, ResourceType
from cdpify.domains.target import (
    AttachedToTargetEvent,
    DetachedFromTargetEvent,
    FilterEntry,
)

from browserrig.core import BrowserError
from browserrig.events import NavigationBlockedEvent

from .policy import DomainNotAllowed, NavigationPolicy

if TYPE_CHECKING:
    from .base import EventSink


class NavigationGuard:
    """Intercept documents before resuming newly created page and frame targets.

    Only our browser context (or an attached target and its descendants) receives
    a policy. Other targets are immediately resumed and detached. Guard sessions
    are separate from inspection sessions and are detached at session exit.
    """

    def __init__(self, policy: NavigationPolicy, emit: EventSink) -> None:
        self._policy = policy
        self._emit = emit
        self._sessions: dict[str, str] = {}
        self._ready: dict[str, asyncio.Event] = {}
        self._targets: set[str] = set()
        self._context: str | None = None
        self._blocked: dict[str, DomainNotAllowed] = {}
        self._failure: Exception | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._client: CdpClient

    async def start(
        self,
        client: CdpClient,
        stack: AsyncExitStack,
        *,
        context: str | None,
        target_id: str | None,
    ) -> None:
        self._client = client
        self._context = context
        if target_id is not None:
            self._targets.add(target_id)
        # Subscribe before any attach command; no document may outrun its listener.
        for kind, handler in (
            (AttachedToTargetEvent, self._attached),
            (RequestPausedEvent, self._request),
            (DetachedFromTargetEvent, self._detached),
        ):
            subscription = client.listen_all(kind)
            await stack.enter_async_context(subscription)
            self._tasks.append(
                asyncio.create_task(self._consume(subscription, handler))
            )
        stack.push_async_callback(self._close)
        await client.target.set_auto_attach(
            auto_attach=True,
            wait_for_debugger_on_start=True,
            flatten=True,
            filter=[FilterEntry(type="page"), FilterEntry(type="iframe")],
        )

    async def check(self, url: str, target_id: str = "") -> None:
        self.raise_if_blocked()
        try:
            self._policy.check(url)
        except DomainNotAllowed as error:
            await self._emit(NavigationBlockedEvent(url=error.url, target_id=target_id))
            raise

    async def watch(self, target_id: str) -> None:
        ready = self._ready.setdefault(target_id, asyncio.Event())
        async with asyncio.timeout(10):
            await ready.wait()
        self.raise_if_blocked()

    def raise_if_blocked(self, target_id: str = "") -> None:
        if self._failure is not None:
            raise BrowserError(
                "Navigation guard failed; reconnect before continuing"
            ) from self._failure
        if error := self._blocked.pop(target_id, None):
            raise error

    async def _consume(
        self,
        subscription: EventSubscription[ReceivedEvent[Any]],
        handler: Callable[[Any, str | None], Awaitable[None]],
    ) -> None:
        try:
            async for received in subscription:
                try:
                    await handler(received.value, received.session_id)
                except CDPCommandError:
                    # Targets may disappear while a command is in flight. A live target
                    # failing setup, however, must never be silently resumed unguarded.
                    targets = await self._client.target.get_targets()
                    live = {info.target_id for info in targets.target_infos}
                    target = (
                        received.value.target_info.target_id
                        if isinstance(received.value, AttachedToTargetEvent)
                        else self._sessions.get(received.session_id or "", "")
                    )
                    if target in live:
                        raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            self._failure = error
            for ready in self._ready.values():
                ready.set()

    async def _attached(self, event: AttachedToTargetEvent, parent: str | None) -> None:
        if (
            parent is not None and parent not in self._sessions
        ) or event.target_info.type not in {"page", "iframe"}:
            return
        cdp = self._client.session(event.session_id)
        info = event.target_info
        target_id = info.target_id
        controlled = parent in self._sessions or (
            info.browser_context_id == self._context
            if self._context is not None
            else target_id in self._targets or info.opener_id in self._targets
        )
        if not controlled:
            await cdp.runtime.run_if_waiting_for_debugger()
            await self._client.target.detach_from_target(session_id=event.session_id)
            return
        # Manual inspection attaches also emit this event. The first auto-attach
        # session owns interception; enabling Fetch on both would pause twice.
        if target_id in self._sessions.values():
            if event.waiting_for_debugger:
                await cdp.runtime.run_if_waiting_for_debugger()
            return
        self._targets.add(target_id)
        self._sessions[event.session_id] = target_id
        await cdp.fetch.enable(
            patterns=[RequestPattern(resource_type=ResourceType.DOCUMENT)]
        )
        await cdp.target.set_auto_attach(
            auto_attach=True,
            wait_for_debugger_on_start=True,
            flatten=True,
            filter=[FilterEntry(type="page"), FilterEntry(type="iframe")],
        )
        await cdp.runtime.run_if_waiting_for_debugger()
        self._ready.setdefault(target_id, asyncio.Event()).set()

    async def _request(self, event: RequestPausedEvent, session_id: str | None) -> None:
        if session_id not in self._sessions:
            return
        assert session_id is not None
        target_id = self._sessions[session_id]
        cdp = self._client.session(session_id)
        try:
            self._policy.check(event.request.url)
        except DomainNotAllowed as error:
            # Store before failing the request: Page.navigate can return immediately.
            self._blocked[target_id] = error
            await cdp.fetch.fail_request(
                request_id=event.request_id, error_reason=ErrorReason.BLOCKED_BY_CLIENT
            )
            await self._emit(NavigationBlockedEvent(url=error.url, target_id=target_id))
        else:
            await cdp.fetch.continue_request(request_id=event.request_id)

    async def _detached(
        self, event: DetachedFromTargetEvent, _parent: str | None
    ) -> None:
        if target_id := self._sessions.pop(event.session_id, None):
            self._ready.pop(target_id, None)

    async def _close(self) -> None:
        try:
            if self._client.is_connected:
                for session_id in tuple(self._sessions):
                    with suppress(CDPCommandError):
                        await self._client.session(session_id).fetch.disable()
                # This detaches our auto-attach sessions and releases pending requests;
                # the browser's normal inspection sessions remain connected.
                with suppress(CDPCommandError):
                    await self._client.target.set_auto_attach(
                        auto_attach=False,
                        wait_for_debugger_on_start=False,
                        flatten=True,
                    )
        finally:
            for task in self._tasks:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
