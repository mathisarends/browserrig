import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from harnessed import ToolError, ToolResult
from harnessed.tracing import record, traced

from browserrig.browser import Browser, BrowserEvents, Tab
from browserrig.core import (
    ActionContext,
    ActionKind,
    BrowserCoordination,
    BrowserError,
    ReadinessPhase,
    ReadinessStatus,
)
from browserrig.events import (
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    PageState,
)
from browserrig.observation import BrowserPerception
from browserrig.readiness import PageReadiness
from browserrig.tools.chains import observes
from browserrig.tools.effects import Effect

from .context import NO_CALL, CallIdentity, ToolAction, ToolActionError
from .dispatch import ActionDispatch
from .policy import ActionProfile, action_profile


class ActionRunner:
    """Serialize one mutation and own its preparation, receipts and failure semantics."""

    def __init__(
        self,
        browser: Browser,
        coordination: BrowserCoordination,
        events: BrowserEvents,
        readiness: PageReadiness,
        observe: BrowserPerception,
        *,
        actions: ActionContext,
        page_change: Callable[[Tab], Awaitable[str]],
        check_action: Callable[[Tab, ActionKind], Awaitable[None]],
    ) -> None:
        self._browser = browser
        self._coordination = coordination
        self._events = events
        self._readiness = readiness
        self._observe = observe
        self._page_change = page_change
        self._check_action = check_action
        self._dispatch = ActionDispatch(browser.tabs, readiness, actions)

    @traced
    async def run(
        self,
        *,
        kind: ActionKind,
        operation: Callable[[Tab], Awaitable[Effect]],
        check: Callable[[Tab], Awaitable[None]] | None = None,
        expects_change: bool = False,
        settle: bool = True,
        action: ToolAction | None = None,
        call: CallIdentity = NO_CALL,
    ) -> ToolResult:
        """Run one mutation once. Its addressed tab cannot change with global focus."""
        profile = action_profile(kind) or ActionProfile()
        record(kind=kind)
        async with self._coordination.exclusive():
            tab = self._browser.active_tab
            action_id = uuid4().hex
            if action is not None:
                action.tab = tab
                action.action_id = action_id
                call = CallIdentity(action.call_id, action.label)
            dispatched = False
            try:
                before = await self._prepare(tab, kind, profile)
                if check is not None:
                    await check(tab)
                await self._check_action(tab, kind)
                if action is None or not profile.preflight:
                    await self._events.emit(
                        ActionStartedEvent(
                            action_id=action_id,
                            kind=kind,
                            target_id=tab.id,
                            document_id=tab.document_id,
                            call_id=call.call_id,
                            label=call.label,
                        )
                    )
                    dispatched = True
                    if action is not None:
                        action.started = True
                followed = ""
                if settle and profile.phase is ReadinessPhase.NAVIGATION:
                    effect, note = await self._dispatch.navigate(
                        tab, action_id, operation
                    )
                else:
                    effect, note, followed = await self._dispatch.dispatch(
                        tab, action_id, operation, profile=profile, settle=settle
                    )
                if action is not None and not action.started:
                    await self.start(action)
                self._check_navigation(tab)
                await self._events.emit(
                    ActionFinishedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                        before=before,
                        after_url=tab.url,
                        prepared_scroll=effect.prepared_scroll,
                        expects_change=expects_change,
                        call_id=call.call_id,
                        label=call.label,
                    )
                )
                return await self._result(
                    tab,
                    profile,
                    effect,
                    followed=followed,
                    note=note,
                    preparation=_preparation(action),
                )
            except asyncio.CancelledError:
                if action is not None:
                    dispatched = action.started
                reason = (
                    "cancelled; side effects may already have occurred"
                    if dispatched
                    else "cancelled"
                )
                await self._fail(
                    tab,
                    action_id,
                    kind,
                    call,
                    dispatched=dispatched,
                    reason=reason,
                    cancelled=True,
                )
                raise
            except Exception as error:
                # Every failed action needs a receipt, including unknown backend errors.
                if action is not None:
                    dispatched = action.started
                reason = (
                    str(error)
                    if isinstance(error, (BrowserError, ToolError))
                    else f"{type(error).__name__}: {error}"
                )
                await self._fail(
                    tab, action_id, kind, call, dispatched=dispatched, reason=reason
                )
                hint = (
                    "; the action may have run. Observe before retrying."
                    if dispatched
                    else ""
                ) + _preparation(action)
                if isinstance(error, ToolActionError):
                    return error.result.with_note(hint) if hint else error.result
                raise ToolError(reason + hint) from error

    async def start(self, action: ToolAction) -> None:
        tab = action.tab
        assert tab is not None
        await self._events.emit(
            ActionStartedEvent(
                action_id=action.action_id,
                kind=action.kind,
                target_id=tab.id,
                document_id=tab.document_id,
                call_id=action.call_id,
                label=action.label,
            )
        )
        action.started = True

    async def _result(
        self,
        tab: Tab,
        profile: ActionProfile,
        effect: Effect,
        *,
        followed: str,
        note: str,
        preparation: str,
    ) -> ToolResult:
        change = ""
        if not effect.break_chain and not note and not followed and profile.check_chain:
            change = await self._page_change(tab)
        result = ToolResult(
            effect.text + followed + note + preparation,
            break_chain=effect.break_chain
            or bool(note)
            or bool(followed)
            or bool(change),
        )
        return (
            result.with_note(change + " Observe before continuing.")
            if change
            else result
        )

    def _check_navigation(self, tab: Tab) -> None:
        tab.check_navigation()
        active = self._browser.active_tab
        if active is not tab:
            active.check_navigation()

    @traced
    async def _prepare(
        self, tab: Tab, kind: ActionKind, profile: ActionProfile
    ) -> PageState:
        """Return the pre-action baseline once the page accepts input."""
        if kind is ActionKind.GO_FORWARD and not await tab.can_go_forward():
            raise BrowserError("Cannot go forward: no next history entry")
        if kind is ActionKind.GO_BACK and not await tab.can_go_back():
            raise BrowserError("No previous history entry")
        if profile.phase is ReadinessPhase.NAVIGATION and tab.dialog:
            raise BrowserError("A JavaScript dialog must be handled first")
        if profile.phase is not ReadinessPhase.AFTER_ACTION:
            # Page management must work even when the current DOM never settles.
            return PageState(url=tab.url, document_id=tab.document_id)
        report = await self._readiness.wait(tab, phase=ReadinessPhase.ACTION)
        if report.status == ReadinessStatus.BLOCKED or (
            report.timed_out and tab.navigation_pending
        ):
            raise BrowserError(report.reason + "; inspect the next observation")
        before = self._observe.snapshot
        if (
            before is not None
            and profile.requires_observation
            and not observes(before, tab)
        ):
            raise BrowserError(
                "The observed tab or document changed; act on the next observation"
            )
        if before is None or before.tab_id != tab.id:
            before = await self._observe.capture(tab)
        return PageState(
            url=before.url,
            document_id=before.document_id,
            fingerprint=before.fingerprint,
            scroll_y=before.scroll_y,
        )

    async def _fail(
        self,
        tab: Tab,
        action_id: str,
        kind: ActionKind,
        call: CallIdentity,
        *,
        dispatched: bool,
        reason: str,
        cancelled: bool = False,
    ) -> None:
        await self._events.emit(
            ActionFailedEvent(
                action_id=action_id,
                kind=kind,
                target_id=tab.id,
                document_id=tab.document_id,
                dispatched=dispatched,
                reason=reason,
                cancelled=cancelled,
                call_id=call.call_id,
                label=call.label,
            )
        )


def _preparation(action: ToolAction | None) -> str:
    if action is None or not action.preparation_notes:
        return ""
    notes = list(action.preparation_notes)
    if action.preparation_omitted:
        notes.append(
            f"{action.preparation_omitted} additional auto-reveal steps omitted."
        )
    return "\n" + "\n".join(notes)
