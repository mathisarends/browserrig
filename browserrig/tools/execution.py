import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from harnessed import Context, Inject, Plugin, ToolError

from browserrig.browser.base import Browser
from browserrig.browser.errors import BrowserError
from browserrig.browser.tab import Tab
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
)
from browserrig.kinds import ActionKind, ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT
from browserrig.observation.plugin import Observe
from browserrig.readiness.models import ReadinessPhase, ReadinessStatus
from browserrig.readiness.plugin import Readiness


@dataclass(frozen=True, slots=True)
class Effect:
    text: str
    prepared_scroll: bool = False


class Actions(Plugin, needs=(Browser, Readiness, Observe)):
    """Own the action transaction: serialization, readiness, dispatch and receipts."""

    events = ACTION_EVENTS
    browser: Browser
    readiness: Readiness
    observe: Observe

    async def setup(
        self,
        ctx: Context,
        browser: Inject[Browser],
        readiness: Inject[Readiness],
        observe: Inject[Observe],
    ) -> None:
        self.browser, self.readiness, self.observe = browser, readiness, observe
        ctx.provide(Actions, self)

    async def run(
        self,
        *,
        kind: ActionKind,
        operation: Callable[[Tab], Awaitable[Effect]],
        expects_change: bool = False,
        settle: bool = True,
    ) -> str:
        """Run one mutation once. Its addressed tab cannot change with global focus."""
        browser, readiness, observe = self.browser, self.readiness, self.observe
        async with browser.action_lock:
            tab = browser.active_tab
            action_id = uuid4().hex
            dispatched = False
            try:
                before = observe.snapshot
                if before is None or before.tab_id != tab.id:
                    before = await observe.capture(tab)
                report = await readiness.wait(tab, phase=ReadinessPhase.ACTION)
                if report.status == ReadinessStatus.BLOCKED:
                    raise BrowserError(report.reason)
                await browser.emit(
                    ActionStartedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                    )
                )
                dispatched = True
                effect = await operation(tab)
                note = ""
                if settle and not tab.closed:
                    phase = (
                        ReadinessPhase.NAVIGATION
                        if kind == ActionKind.NAVIGATE
                        else ReadinessPhase.ACTION
                    )
                    try:
                        report = await readiness.wait(tab, phase=phase)
                        if report.status != ReadinessStatus.READY:
                            note = (
                                f" Action executed; readiness is {report.status}: {report.reason}."
                            )
                    except BrowserError as error:
                        note = (
                            f" Action executed; follow-up observation is unavailable: {error}. "
                            "Do not repeat blindly."
                        )
                await browser.emit(
                    ActionFinishedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                        before_url=before.url,
                        after_url=tab.url,
                        before_document=before.document_id,
                        before_fingerprint=before.fingerprint,
                        before_scroll_y=before.scroll_y,
                        prepared_scroll=effect.prepared_scroll,
                        expects_change=expects_change,
                    )
                )
                return effect.text + note
            except asyncio.CancelledError:
                await browser.emit(
                    ActionFailedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                        dispatched=dispatched,
                        reason="cancelled; side effects may already have occurred"
                        if dispatched
                        else "cancelled",
                    )
                )
                raise
            except Exception as error:
                reason = str(error) if isinstance(error, BrowserError) else type(error).__name__
                await browser.emit(
                    ActionFailedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                        dispatched=dispatched,
                        reason=reason,
                    )
                )
                raise ToolError(
                    reason
                    + ("; the action may have run. Observe before retrying." if dispatched else "")
                ) from error

    async def element_call(
        self,
        *,
        tab: Tab,
        ref: str,
        operation: ElementOperation,
        value: object = None,
        by_value: bool = True,
    ) -> Any:
        frame, element = await self.observe.element(tab, ref)
        assert self.observe.snapshot is not None
        return await frame.call(
            ELEMENT_SCRIPT,
            self.observe.snapshot.id,
            element.index,
            operation,
            value,
            by_value=by_value,
        )
