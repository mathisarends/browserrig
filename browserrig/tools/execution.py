import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import cast
from uuid import uuid4

from harnessed import (
    Instructions,
    Plugin,
    PluginState,
    SystemPrompt,
    ToolError,
    ToolResult,
    hook,
)
from harnessed.hooks import ExecuteTool, Next, ReviewToolResult
from harnessed.kernel import PluginScope, needs
from harnessed.tracing import record, span, traced

from browserrig.browser import Browser, BrowserEvents, Tab
from browserrig.core import (
    ActionKind,
    BrowserCoordination,
    BrowserError,
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
from browserrig.observation import BrowserPerception
from browserrig.readiness import Readiness

from .chains import (
    ActionChainPolicy,
    DomActionChains,
    observes,
    probe_change,
    stop_on_failure,
)
from .effects import Effect
from .intents import Intent, Perform
from .targeting import Targeting

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
# Page input that opens a tab, like a target=_blank link, leads into it as in Chrome.
_FOLLOWED_KINDS = _POINTER_KINDS | _CHAINABLE_KINDS
# How long input that asked for a new tab waits for the browser to open it.
_TAB_OPEN_SECONDS = 3.0


_INSTRUCTIONS = Instructions(
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


@dataclass
class _Mount:
    context: PluginScope | None = None
    targeting: Targeting | None = None


class Actions(Plugin, slot="browserrig.actions", provides=True):
    """Own the action transaction: serialization, readiness, dispatch and receipts."""

    events = ACTION_EVENTS
    _mount = PluginState(_Mount)
    browser = needs(Browser)
    _coordination = needs(BrowserCoordination)
    _events = needs(BrowserEvents)
    readiness = needs(Readiness)
    observe = needs(BrowserPerception)

    def __init__(self, *, chain_policy: ActionChainPolicy | None = None) -> None:
        super().__init__()
        self.chain_policy = (
            chain_policy if chain_policy is not None else DomActionChains()
        )

    async def setup(self, scope: PluginScope) -> None:
        self._mount.context = scope
        self._mount.targeting = Targeting(self.browser, self.observe, scope)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @traced
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
        record(kind=kind)
        async with self._coordination.exclusive():
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
                followed = ""
                if settle and kind in _NAVIGATION_KINDS:
                    effect, note = await self._navigate(tab, action_id, operation)
                else:
                    effect, note, followed = await self._dispatch(
                        tab, kind, action_id, operation, settle=settle
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
                if (
                    not effect.break_chain
                    and not note
                    and not followed
                    and kind in _CHAINABLE_KINDS
                ):
                    change = await self.page_change(tab)
                result = ToolResult(
                    effect.text + followed + note,
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
            except asyncio.CancelledError:
                reason = (
                    "cancelled; side effects may already have occurred"
                    if dispatched
                    else "cancelled"
                )
                await self._fail(
                    tab, action_id, kind, dispatched, reason, cancelled=True
                )
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

    @traced
    async def stage[R](
        self, intent: Intent, tab: Tab, step: Callable[[], Awaitable[R]]
    ) -> R:
        """Run `step`, which does what `intent` describes, letting plugins stage it."""
        record(intent=type(intent).__name__)
        context = self._mount.context
        assert context is not None
        performed = Perform(intent, tab, self.browser.input.action_id)
        return cast(R, await context.dispatch(performed, default=step))

    @traced
    async def page_change(self, tab: Tab, *, after_input: bool = True) -> str:
        """A comparison probe must never replace the refs or image the model acted on."""
        if tab.closed or self.browser.active_tab.id != tab.id:
            return "The active tab changed."
        try:
            if not after_input:
                return await probe_change(self.observe, tab)
            return await self.chain_policy.check(self.observe, tab)
        except Exception:  # pylint: disable=broad-exception-caught
            # Successful input remains successful even if comparison fails.
            return "The page could not be checked after input."

    async def element_point(
        self, *, tab: Tab, ref: str, scroll: bool = True
    ) -> ElementPoint:
        """Reveal a ref and return a hit-tested point with an action-scoped aim."""
        targeting = self._mount.targeting
        assert targeting is not None
        return await targeting.locate(tab=tab, ref=ref, scroll=scroll)

    @hook(ExecuteTool, ReviewToolResult)
    async def _execute_browser_result(
        self, event: ExecuteTool | ReviewToolResult, next_: Next[ToolResult]
    ) -> ToolResult:
        # Set the signal before the execution receipt is persisted, including on errors.
        return stop_on_failure(await next_(), event.tool)

    @traced
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
            and not observes(before, tab)
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

    @traced
    async def _settle(self, tab: Tab, kind: ActionKind, started: float) -> str:
        phase = (
            ReadinessPhase.NAVIGATION
            if kind in _NAVIGATION_KINDS
            else ReadinessPhase.AFTER_ACTION
        )
        try:
            report = await self.readiness.wait(tab, phase=phase, since=started)
        except BrowserError as error:
            return (
                f" Action executed; follow-up observation is unavailable: {error}. "
                "Do not repeat blindly."
            )
        if report.status != ReadinessStatus.READY:
            return f" Action executed; readiness is {report.status}: {report.reason}."
        return ""

    async def _dispatch(
        self,
        tab: Tab,
        kind: ActionKind,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
        *,
        settle: bool,
    ) -> tuple[Effect, str, str]:
        """Run input in `tab`, then wait for its page, or for a tab the input opened.

        Returns the effect, a readiness note and a note on the tab that opened.
        """
        started = monotonic()
        mark = self.browser.tabs.openings
        with self.browser.input.action(action_id), span("browserrig.operation"):
            effect = await operation(tab)
        settled = settle and not tab.closed
        note = (
            await self._settle(tab, kind, started)
            if settled and not effect.opens_tab
            else ""
        )
        if kind not in _FOLLOWED_KINDS or tab.closed:
            return effect, note, ""
        with self.browser.input.action(action_id):
            followed = await self._follow(tab, mark, expected=effect.opens_tab)
        if effect.opens_tab and not followed:
            # Nothing opened, so the input acted in this tab instead.
            if settled:
                note = await self._settle(tab, kind, started)
            followed = " No new tab opened; the input acted in this tab."
        return effect, note, followed

    @traced
    async def _follow(self, tab: Tab, mark: int, *, expected: bool) -> str:
        """Activate a tab the input opened and wait for its page, as Chrome shows it.

        Input that asked for a new tab gives the browser a moment to open it; other input
        has already settled, so a tab it opened is attached by now.
        """
        opened = await self.browser.tabs.opened_since(
            mark, timeout=_TAB_OPEN_SECONDS if expected else 0
        )
        if opened is None:
            return ""
        await self.browser.tabs.activate(opened.id)
        report = await self.readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
        note = (
            f" It opened tab {opened.id}, which is now active; "
            f"the previous tab is {tab.id}."
        )
        if report.status != ReadinessStatus.READY:
            note += f" Readiness is {report.status}: {report.reason}."
        return note

    @traced
    async def _navigate(
        self,
        tab: Tab,
        action_id: str,
        operation: Callable[[Tab], Awaitable[Effect]],
    ) -> tuple[Effect, str]:
        effects: list[Effect] = []

        async def dispatch() -> None:
            with self.browser.input.action(action_id), span("browserrig.operation"):
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
        self,
        tab: Tab,
        action_id: str,
        kind: ActionKind,
        dispatched: bool,
        reason: str,
        *,
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
            )
        )
