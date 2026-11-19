import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from uuid import uuid4

from harnessed import ToolError, ToolResult
from harnessed.kernel import PluginScope
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
from browserrig.observation import BrowserPerception, CapturedImage
from browserrig.readiness import PageReadiness
from browserrig.tools.effects import Effect

from .context import NO_CALL, CallIdentity, ToolAction, ToolActionError
from .dispatch import ActionDispatch, Dispatched
from .policy import COORDINATE_KINDS, ActionProfile, action_profile
from .telemetry import operation_span, record_operation, record_target


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
        scope: PluginScope,
        redact: Callable[[str], str],
    ) -> None:
        self._browser = browser
        self._coordination = coordination
        self._events = events
        self._readiness = readiness
        self._observe = observe
        self._page_change = page_change
        self._check_action = check_action
        self._scope = scope
        self._redact = redact
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
        arguments: Mapping[str, object] | None = None,
    ) -> ToolResult:
        """Run one mutation once. Its addressed tab cannot change with global focus."""
        profile = action_profile(kind) or ActionProfile()
        record(kind=kind)
        async with self._coordination.exclusive(), AsyncExitStack() as stack:
            tab = self._browser.active_tab
            action_id = uuid4().hex
            if action is not None:
                action.tab = tab
                action.action_id = action_id
                call = CallIdentity(action.call_id, action.label, action.tool_name)
            stack.enter_context(
                operation_span(
                    self._scope,
                    **{
                        "browserrig.action.id": action_id,
                        "browserrig.action.kind": kind,
                        "browserrig.tool.name": call.tool_name or kind.value,
                        "browserrig.tab_id": tab.id,
                        "browserrig.document_id": tab.document_id,
                    },
                )
            )
            self._record_context(call, kind, arguments)
            dispatched = False
            checking = True
            try:
                before = await self._prepare(tab, kind, profile)
                if check is not None:
                    await check(tab)
                await self._check_action(tab, kind)
                checking = False
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
                effect, note, followed = await self._dispatch_action(
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
                result = await self._result(
                    tab,
                    profile,
                    effect,
                    followed=followed,
                    note=note,
                    preparation=_preparation(action),
                )
                self._record_outcome(
                    "blocked" if effect.blocked_reason else "dispatched",
                    started=True,
                    reason=effect.blocked_reason,
                )
                return result
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
                    outcome="cancelled",
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
                    tab,
                    action_id,
                    kind,
                    call,
                    dispatched=dispatched,
                    reason=reason,
                    outcome="blocked"
                    if checking and isinstance(error, (BrowserError, ToolError))
                    else "failed",
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

    async def _dispatch_action(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
        *,
        profile: ActionProfile,
        settle: bool,
    ) -> Dispatched:
        if settle and profile.phase is ReadinessPhase.NAVIGATION:
            effect, note = await self._dispatch.navigate(tab, action_id, operation)
            return Dispatched(effect, note, "")
        return await self._dispatch.dispatch(
            tab, action_id, operation, profile=profile, settle=settle
        )

    def _record_context(
        self,
        call: CallIdentity,
        kind: ActionKind,
        arguments: Mapping[str, object] | None,
    ) -> None:
        if call.call_id:
            record_operation(**{"tool.call_id": call.call_id})
        snapshot = self._observe.snapshot
        if snapshot is not None:
            record_operation(**{"observation.id": snapshot.id})
        source = self._observe.coordinates
        if kind in COORDINATE_KINDS and source is not None:
            record_operation(
                **{
                    "input.space": "screenshot"
                    if isinstance(source, CapturedImage)
                    else "viewport"
                }
            )
        if isinstance(source, CapturedImage):
            record_operation(**{"screenshot.id": source.id})
            if source.asset_id is not None:
                record_operation(**{"screenshot.asset_id": source.asset_id})
        if arguments:
            record_target(kind, arguments)

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
        if profile.phase is not ReadinessPhase.AFTER_ACTION:
            # Page management must work even when the current DOM never settles.
            return PageState(url=tab.url, document_id=tab.document_id)
        report = await self._readiness.wait(tab, phase=ReadinessPhase.ACTION)
        if report.status == ReadinessStatus.BLOCKED or (
            report.timed_out and tab.navigation_pending
        ):
            raise BrowserError(report.reason + "; inspect the next observation")
        before = self._observe.snapshot
        if before is None or (
            before.tab_id != tab.id and not profile.requires_observation
        ):
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
        outcome: str,
    ) -> None:
        self._record_outcome(outcome, started=dispatched, reason=reason)
        await self._events.emit(
            ActionFailedEvent(
                action_id=action_id,
                kind=kind,
                target_id=tab.id,
                document_id=tab.document_id,
                dispatched=dispatched,
                reason=reason,
                cancelled=outcome == "cancelled",
                call_id=call.call_id,
                label=call.label,
            )
        )

    def _record_outcome(self, outcome: str, *, started: bool, reason: str) -> None:
        record_operation(**{"action.outcome": outcome, "action.started": started})
        if reason:
            record_operation(**{"action.reason": self._redact(reason)})


def _preparation(action: ToolAction | None) -> str:
    if action is None or not action.preparation_notes:
        return ""
    notes = list(action.preparation_notes)
    if action.preparation_omitted:
        notes.append(
            f"{action.preparation_omitted} additional auto-reveal steps omitted."
        )
    return "\n" + "\n".join(notes)
