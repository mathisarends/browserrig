import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from harnessed import Inject, Plugin, ToolError

from browserrig.browser.base import Browser
from browserrig.browser.tab import Frame, Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, ElementPoint
from browserrig.core.kinds import ActionKind, ElementOperation
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    ElementHighlightedEvent,
    PageState,
)
from browserrig.observation.models import Element, Snapshot
from browserrig.observation.plugin import Observe
from browserrig.readiness.models import ReadinessPhase, ReadinessStatus
from browserrig.readiness.plugin import Readiness
from browserrig.scripts import ELEMENT
from browserrig.scripts.models import ElementArgs

from .scrolling import prepare_element

# Pointer actions aim at coordinates from the last observation, so it must still be current.
_POINTER_KINDS = frozenset({ActionKind.CLICK, ActionKind.DOUBLE_CLICK, ActionKind.DRAG})


@dataclass(frozen=True, slots=True)
class Effect:
    text: str
    prepared_scroll: bool = False


class Actions(Plugin, provides=True, needs=(Browser, Readiness, Observe)):
    """Own the action transaction: serialization, readiness, dispatch and receipts."""

    events = ACTION_EVENTS
    browser: Inject[Browser]
    readiness: Inject[Readiness]
    observe: Inject[Observe]

    async def run(
        self,
        *,
        kind: ActionKind,
        operation: Callable[[Tab], Awaitable[Effect]],
        check: Callable[[Tab], Awaitable[None]] | None = None,
        expects_change: bool = False,
        settle: bool = True,
    ) -> str:
        """Run one mutation once. Its addressed tab cannot change with global focus."""
        async with self.browser.action_lock:
            tab = self.browser.active_tab
            action_id = uuid4().hex
            dispatched = False
            try:
                before = await self._prepare(tab, kind)
                if check is not None:
                    await check(tab)
                await self.browser.emit(
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
                note = await self._settle(tab, kind) if settle and not tab.closed else ""
                await self.browser.emit(
                    ActionFinishedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                        before=before,
                        after_url=tab.url,
                        prepared_scroll=effect.prepared_scroll,
                        expects_change=expects_change,
                    )
                )
                return effect.text + note
            except asyncio.CancelledError:
                reason = (
                    "cancelled; side effects may already have occurred"
                    if dispatched
                    else "cancelled"
                )
                await self._fail(tab, action_id, kind, dispatched, reason)
                raise
            except Exception as error:
                reason = (
                    str(error)
                    if isinstance(error, (BrowserError, ToolError))
                    else f"{type(error).__name__}: {error}"
                )
                await self._fail(tab, action_id, kind, dispatched, reason)
                hint = "; the action may have run. Observe before retrying." if dispatched else ""
                raise ToolError(reason + hint) from error

    async def _prepare(self, tab: Tab, kind: ActionKind) -> PageState:
        """Return the pre-action baseline once the page accepts input."""
        if kind == ActionKind.TAB:
            # Tab management must work even when the current page has a blocking dialog.
            return PageState(url=tab.url, document_id=tab.document_id)
        await tab.sync_document()
        before = self.observe.snapshot
        if before is not None and kind in _POINTER_KINDS and not _observes(before, tab):
            raise BrowserError("The observed tab or document changed; observe before pointing")
        if before is None or before.tab_id != tab.id:
            before = await self.observe.capture(tab)
        report = await self.readiness.wait(tab, phase=ReadinessPhase.ACTION)
        if report.status == ReadinessStatus.BLOCKED:
            raise BrowserError(report.reason)
        return PageState(
            url=before.url,
            document_id=before.document_id,
            fingerprint=before.fingerprint,
            scroll_y=before.scroll_y,
        )

    async def _settle(self, tab: Tab, kind: ActionKind) -> str:
        phase = ReadinessPhase.NAVIGATION if kind == ActionKind.NAVIGATE else ReadinessPhase.ACTION
        try:
            report = await self.readiness.wait(tab, phase=phase)
        except BrowserError as error:
            return (
                f" Action executed; follow-up observation is unavailable: {error}. "
                "Do not repeat blindly."
            )
        if report.status != ReadinessStatus.READY:
            return f" Action executed; readiness is {report.status}: {report.reason}."
        return ""

    async def _fail(
        self, tab: Tab, action_id: str, kind: ActionKind, dispatched: bool, reason: str
    ) -> None:
        await self.browser.emit(
            ActionFailedEvent(
                action_id=action_id,
                kind=kind,
                target_id=tab.id,
                document_id=tab.document_id,
                dispatched=dispatched,
                reason=reason,
            )
        )

    async def element_call(
        self,
        *,
        tab: Tab,
        ref: str,
        operation: ElementOperation,
        value: object = None,
        by_value: bool = True,
    ) -> Any:
        if operation in {
            ElementOperation.SELECT,
            ElementOperation.SET_VALUE,
            ElementOperation.NODE,
        }:
            await self.element_point(tab=tab, ref=ref)
        frame, element = await self.observe.element(tab, ref)
        return await self._call(frame, element, operation, value, by_value=by_value)

    async def element_point(self, *, tab: Tab, ref: str, scroll: bool = True) -> ElementPoint:
        frame, element = await self.observe.element(tab, ref)
        scrolled = False
        if scroll:
            snapshot = self.observe.snapshot
            assert snapshot is not None
            scrolled = await prepare_element(self.browser, tab, snapshot, element)
            # Wheel input may have moved ancestor documents; refresh their transforms.
            frame, _ = await self.observe.element(tab, ref)
        current = await self._locate(frame, element)
        x, y = frame.projection.point(current.x, current.y)
        await frame.check_point(x, y)
        bounds = frame.projection.box(current.bounds) if current.bounds is not None else None
        if bounds is not None:
            await tab.input.emit(
                ElementHighlightedEvent(
                    ref=ref, x=bounds.x, y=bounds.y, width=bounds.width, height=bounds.height
                )
            )
        return ElementPoint(x=x, y=y, scrolled=scrolled, bounds=bounds)

    async def _locate(self, frame: Frame, element: Element) -> ElementPoint:
        clip = frame.local_clip
        raw = await self._call(frame, element, ElementOperation.POINT, False, clip)
        return ElementPoint.model_validate(raw)

    async def _call(
        self,
        frame: Frame,
        element: Element,
        operation: ElementOperation,
        value: object = None,
        clip: Bounds | None = None,
        *,
        by_value: bool = True,
    ) -> Any:
        snapshot = self.observe.snapshot
        assert snapshot is not None
        return await frame.run(
            ELEMENT,
            ElementArgs(
                token=snapshot.id, index=element.index, operation=operation, value=value, clip=clip
            ),
            by_value=by_value,
            user_gesture=True,
        )


def _observes(snapshot: Snapshot, tab: Tab) -> bool:
    return snapshot.tab_id == tab.id and snapshot.document_id == tab.document_id
