import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol, cast
from uuid import uuid4

from harnessed import (
    Context,
    Inject,
    Plugin,
    PluginState,
    SystemSection,
    ToolError,
    ToolInfo,
    ToolResult,
    ToolStatus,
    hook,
)
from harnessed.hooks import ExecuteTool, Next, ReviewToolResult

from browserrig.browser import Browser, BrowserEvents, Tab
from browserrig.core import (
    ActionKind,
    BrowserError,
    BrowserToolMetadata,
    ElementPoint,
    ReadinessPhase,
    ReadinessStatus,
)
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
    PageState,
)
from browserrig.observation import Observe, Snapshot, decision_change
from browserrig.readiness import Readiness

from .intents import Intent, Perform, TargetLocated
from .scrolling import prepare_element

# Pointer actions aim at coordinates from the last observation, so it must still be current.
_POINTER_KINDS = frozenset(
    {
        ActionKind.CLICK,
        ActionKind.CLICK_AT,
        ActionKind.MOVE_MOUSE,
        ActionKind.DOUBLE_CLICK,
        ActionKind.DRAG,
        ActionKind.DRAG_AT,
    }
)
_CHAINABLE_KINDS = {
    ActionKind.CLICK,
    ActionKind.DOUBLE_CLICK,
    ActionKind.TYPE,
    ActionKind.PRESS,
    ActionKind.SELECT,
    ActionKind.SET_DATE,
}
_TAB_KINDS = {
    ActionKind.TAB,
    ActionKind.OPEN_TAB,
    ActionKind.SWITCH_TAB,
    ActionKind.CLOSE_TAB,
    ActionKind.OPEN_FILE,
    ActionKind.OPEN_DOWNLOADED_FILE,
}
_NAVIGATION_KINDS = {
    ActionKind.NAVIGATE,
    ActionKind.SEARCH,
    ActionKind.GO_BACK,
    ActionKind.GO_FORWARD,
    ActionKind.RELOAD,
}


@dataclass
class _Mount:
    context: Context | None = None


@dataclass(frozen=True, slots=True)
class Effect:
    text: str
    prepared_scroll: bool = False
    break_chain: bool = False


class ActionChainPolicy(Protocol):
    async def check(self, observe: Observe, tab: Tab) -> str:
        """Empty means continue; otherwise explain why a new observation is needed."""
        ...


class ObserveAfterInput:
    async def check(self, _observe: Observe, _tab: Tab) -> str:
        return "A fresh observation is required after this input."


class DomActionChains:
    async def check(self, observe: Observe, tab: Tab) -> str:
        before = observe.snapshot
        if before is None:
            return "A fresh observation is required after this input."
        after = await observe.probe(tab)
        if after.readiness != ReadinessStatus.READY or after.limitations:
            return "The page could not be checked completely after input."
        return decision_change(before, after)


class Actions(
    Plugin, provides=True, needs=(Browser, BrowserEvents, Readiness, Observe)
):
    """Own the action transaction: serialization, readiness, dispatch and receipts."""

    events = ACTION_EVENTS
    _mount = PluginState(_Mount)
    browser: Inject[Browser]
    _events: Inject[BrowserEvents]
    readiness: Inject[Readiness]
    observe: Inject[Observe]

    def __init__(self, *, chain_policy: ActionChainPolicy | None = None) -> None:
        super().__init__()
        self.chain_policy = chain_policy or DomActionChains()

    async def setup(self, ctx: Context) -> None:
        self._mount.context = ctx

    chains = SystemSection(
        title="Browser action chains",
        text=(
            "Combine actions only when no intermediate observation is needed, and put "
            "submission last. Inputs may continue while the page remains suitable. "
            "Navigation, tab changes, scrolling, "
            "drags, coordinates, JavaScript, uploads, dialogs, waiting and screenshot end the "
            "remaining chain. Use coordinate actions alone with a fresh screenshot. A navigation, "
            "new menu, suggestions, modal, alert or input failure interrupts remaining actions; "
            "skipped calls were not executed. Inspect the next observation before continuing."
        ),
    )

    async def run(
        self,
        *,
        kind: ActionKind,
        operation: Callable[[Tab], Awaitable[Effect]],
        check: Callable[[Tab], Awaitable[None]] | None = None,
        expects_change: bool = False,
        settle: bool = True,
    ) -> ToolResult:
        """Run one mutation once. Its addressed tab cannot change with global focus."""
        async with self.browser.action_lock:
            tab = self.browser.active_tab
            action_id = uuid4().hex
            dispatched = False
            try:
                before = await self._prepare(tab, kind)
                if check is not None:
                    await check(tab)
                await self._events.emit(
                    ActionStartedEvent(
                        action_id=action_id,
                        kind=kind,
                        target_id=tab.id,
                        document_id=tab.document_id,
                    )
                )
                dispatched = True
                if settle and kind in _NAVIGATION_KINDS:
                    effect, note = await self._navigate(tab, action_id, operation)
                else:
                    with self.browser.input.action(action_id):
                        effect = await operation(tab)
                    note = (
                        await self._settle(tab, kind)
                        if settle and not tab.closed
                        else ""
                    )
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
                    )
                )
                change = ""
                if not effect.break_chain and not note and kind in _CHAINABLE_KINDS:
                    change = await self.page_change(tab)
                result = ToolResult(
                    effect.text + note,
                    break_chain=effect.break_chain or bool(note) or bool(change),
                )
                return (
                    result.with_note(change + " Observe before continuing.")
                    if change
                    else result
                )
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
                hint = (
                    "; the action may have run. Observe before retrying."
                    if dispatched
                    else ""
                )
                raise ToolError(reason + hint) from error

    async def stage[R](
        self, intent: Intent, tab: Tab, step: Callable[[], Awaitable[R]]
    ) -> R:
        """Run `step`, which does what `intent` describes, letting plugins stage it."""
        context = self._mount.context
        assert context is not None
        performed = Perform(intent, tab, self.browser.input.action_id)
        return cast(R, await context.dispatch(performed, default=step))

    async def page_change(self, tab: Tab, *, after_input: bool = True) -> str:
        """A comparison probe must never replace the refs or image the model acted on."""
        if tab.closed or self.browser.active_tab.id != tab.id:
            return "The active tab changed."
        try:
            policy = self.chain_policy if after_input else DomActionChains()
            return await policy.check(self.observe, tab)
        except Exception:  # pylint: disable=broad-exception-caught
            # Successful input remains successful even if comparison fails.
            return "The page could not be checked after input."

    async def element_point(
        self, *, tab: Tab, ref: str, scroll: bool = True
    ) -> ElementPoint:
        """Reveal a ref with wheel input, then return a hit-tested point.

        Plugins learn about the target through `TargetLocated`.

        Use `scroll=False` to re-check the target after hover or other input moved it.
        """
        handle = await self.observe.element(tab, ref)
        scrolled = False
        if scroll:
            scrolled = await prepare_element(tab, handle, self.browser.mouse)
            # Wheel input may have moved ancestor documents; refresh their transforms.
            handle = await self.observe.element(tab, ref)
        point = await handle.locate()
        context = self._mount.context
        if point.bounds is not None and context is not None:
            await context.dispatch(
                TargetLocated(tab, ref, point.bounds, self.browser.input.action_id)
            )
        return point.model_copy(update={"scrolled": scrolled})

    @hook(ExecuteTool)
    async def _execute_browser_result(
        self, event: ExecuteTool, next_: Next[ToolResult]
    ) -> ToolResult:
        # Set the signal before the execution receipt is persisted, including on errors.
        return _stop_on_failure(await next_(), event.tool)

    @hook(ReviewToolResult)
    async def _review_browser_result(
        self, event: ReviewToolResult, next_: Next[ToolResult]
    ) -> ToolResult:
        return _stop_on_failure(await next_(), event.tool)

    async def _prepare(self, tab: Tab, kind: ActionKind) -> PageState:
        """Return the pre-action baseline once the page accepts input."""
        if kind in _NAVIGATION_KINDS and tab.dialog:
            raise BrowserError("A JavaScript dialog must be handled first")
        if kind in _TAB_KINDS | _NAVIGATION_KINDS:
            # Page management must work even when the current DOM never settles.
            return PageState(url=tab.url, document_id=tab.document_id)
        report = await self.readiness.wait(tab, phase=ReadinessPhase.ACTION)
        if report.status == ReadinessStatus.BLOCKED or (
            report.timed_out and tab.navigation_pending
        ):
            raise BrowserError(report.reason + "; inspect the next observation")
        before = self.observe.snapshot
        if (
            before is not None
            and kind in _POINTER_KINDS | _CHAINABLE_KINDS
            and not _observes(before, tab)
        ):
            raise BrowserError(
                "The observed tab or document changed; act on the next observation"
            )
        if before is None or before.tab_id != tab.id:
            before = await self.observe.capture(tab)
        return PageState(
            url=before.url,
            document_id=before.document_id,
            fingerprint=before.fingerprint,
            scroll_y=before.scroll_y,
        )

    async def _settle(self, tab: Tab, kind: ActionKind) -> str:
        phase = (
            ReadinessPhase.NAVIGATION
            if kind in _NAVIGATION_KINDS
            else ReadinessPhase.AFTER_ACTION
        )
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

    async def _navigate(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
    ) -> tuple[Effect, str]:
        effects: list[Effect] = []

        async def dispatch() -> None:
            with self.browser.input.action(action_id):
                effects.append(await operation(tab))

        report = await self.readiness.wait(
            tab, phase=ReadinessPhase.NAVIGATION, dispatch=dispatch
        )
        effect = (
            effects[0]
            if effects
            else Effect("Navigation requested; completion is not confirmed.")
        )
        note = (
            ""
            if report.status == ReadinessStatus.READY
            else f" Readiness is {report.status}: {report.reason}."
        )
        return effect, note

    async def _fail(
        self, tab: Tab, action_id: str, kind: ActionKind, dispatched: bool, reason: str
    ) -> None:
        await self._events.emit(
            ActionFailedEvent(
                action_id=action_id,
                kind=kind,
                target_id=tab.id,
                document_id=tab.document_id,
                dispatched=dispatched,
                reason=reason,
            )
        )


def _stop_on_failure(result: ToolResult, tool: ToolInfo | None) -> ToolResult:
    metadata = tool.metadata.get(BrowserToolMetadata) if tool else None
    # Calls denied, disabled or skipped before execution retain native approval semantics.
    if (
        metadata is not None
        and result.is_error
        and result.status
        not in {ToolStatus.DENIED, ToolStatus.UNAVAILABLE, ToolStatus.SKIPPED}
    ):
        return replace(result, break_chain=True)
    return result


def _observes(snapshot: Snapshot, tab: Tab) -> bool:
    return snapshot.tab_id == tab.id and snapshot.document_id == tab.document_id
