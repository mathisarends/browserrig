import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from harnessed import Inject, Plugin, ToolError

from browserrig.browser.base import Browser
from browserrig.browser.errors import BrowserError
from browserrig.browser.models import ElementPoint
from browserrig.browser.tab import Tab
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    ElementHighlightedEvent,
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


class Actions(Plugin, provides=True):
    events = ACTION_EVENTS
    browser: Inject[Browser]
    readiness: Inject[Readiness]
    observe: Inject[Observe]

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
                await tab.main_frame()
                before = observe.snapshot
                if (
                    before is not None
                    and kind
                    in {
                        ActionKind.CLICK,
                        ActionKind.DOUBLE_CLICK,
                        ActionKind.DRAG,
                    }
                    and (before.tab_id != tab.id or before.document_id != tab.document_id)
                ):
                    raise BrowserError(
                        "The observed tab or document changed; observe before pointing"
                    )
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
                with tab.input.action(action_id):
                    effect = await operation(tab)
                note = ""
                if settle and not tab.closed:
                    note = await self._settle(tab, kind)
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

    async def _settle(self, tab: Tab, kind: ActionKind) -> str:
        phase = ReadinessPhase.NAVIGATION if kind == ActionKind.NAVIGATE else ReadinessPhase.ACTION
        try:
            report = await self.readiness.wait(tab, phase=phase)
            if report.status != ReadinessStatus.READY:
                return f" Action executed; readiness is {report.status}: {report.reason}."
        except BrowserError as error:
            return (
                f" Action executed; follow-up observation is unavailable: {error}. "
                "Do not repeat blindly."
            )
        return ""

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

    async def element_point(self, *, tab: Tab, ref: str, scroll: bool = True) -> ElementPoint:
        frame, element = await self.observe.element(tab, ref)
        assert self.observe.snapshot is not None
        raw = await frame.call(
            ELEMENT_SCRIPT,
            self.observe.snapshot.id,
            element.index,
            ElementOperation.POINT,
            scroll,
            frame.local_clip.model_dump() if frame.local_clip else None,
        )
        point = ElementPoint.model_validate(raw)
        # scrollIntoView may have moved ancestor documents; refresh their transforms.
        if scroll:
            frame, _ = await self.observe.element(tab, ref)
            raw = await frame.call(
                ELEMENT_SCRIPT,
                self.observe.snapshot.id,
                element.index,
                ElementOperation.POINT,
                False,
                frame.local_clip.model_dump() if frame.local_clip else None,
            )
            current = ElementPoint.model_validate(raw)
        else:
            current = point
        x, y = frame.projection.point(current.x, current.y)
        await frame.check_point(x, y)
        bounds = frame.projection.box(current.bounds) if current.bounds is not None else None
        if bounds is not None:
            await tab.input.emit(
                ElementHighlightedEvent(
                    ref=ref, x=bounds.x, y=bounds.y, width=bounds.width, height=bounds.height
                )
            )
        return ElementPoint(x=x, y=y, scrolled=point.scrolled, bounds=bounds)
