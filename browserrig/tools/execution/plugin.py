from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from harnessed import Instructions, Plugin, PluginState, SystemPrompt, ToolResult, hook
from harnessed.hooks import ExecuteTool, Next, ReviewToolResult
from harnessed.kernel import PluginScope, needs
from harnessed.tracing import record, traced

from browserrig.browser import Browser, BrowserEvents, Tab
from browserrig.core import (
    ActionKind,
    BrowserCoordination,
    BrowserToolCall,
    ElementPoint,
)
from browserrig.events import ACTION_EVENTS
from browserrig.observation import BrowserPerception
from browserrig.readiness import Readiness
from browserrig.tools.chains import (
    ActionChainPolicy,
    ObserveAfterInput,
    probe_change,
    stop_on_failure,
)
from browserrig.tools.effects import Effect
from browserrig.tools.intents import Intent, Perform
from browserrig.tools.targeting import Targeting

from .invocation import ToolExecution
from .transaction import ActionRunner


@dataclass
class _Mount:
    context: PluginScope | None = None
    targeting: Targeting | None = None
    runner: ActionRunner | None = None
    invocation: ToolExecution | None = None


class Actions(Plugin, slot="browserrig.actions", provides=True):
    """Expose browser action services and connect tool calls to their execution lifecycle."""

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
            chain_policy if chain_policy is not None else ObserveAfterInput()
        )

    async def setup(self, scope: PluginScope) -> None:
        self._mount.context = scope
        self._mount.targeting = Targeting(self.browser, self.observe, scope)
        self._mount.runner = ActionRunner(
            self.browser,
            self._coordination,
            self._events,
            self.readiness,
            self.observe,
            page_change=self.page_change,
        )
        self._mount.invocation = ToolExecution(self._runner, self._coordination)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Browser action chains", text=self.chain_policy.instructions()
            )
        )

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
        """Run an explicitly managed operation outside an automatically wrapped tool."""
        record(kind=kind)
        return await self._runner.run(
            kind=kind,
            operation=operation,
            check=check,
            expects_change=expects_change,
            settle=settle,
        )

    @traced
    async def stage[R](
        self, intent: Intent, tab: Tab, step: Callable[[], Awaitable[R]]
    ) -> R:
        """Run `step`, which does what `intent` describes, letting plugins stage it."""
        record(intent=type(intent).__name__)
        action = self._invocation.context.current
        if action is not None and not action.started:
            await self._runner.start(action)
        context = self._mount.context
        assert context is not None
        performed = Perform(intent, tab, self.browser.input.action_id)
        return cast(R, await context.dispatch(performed, default=step))

    @traced
    async def page_change(
        self, tab: Tab | None = None, *, after_input: bool = True
    ) -> str:
        """A comparison probe must never replace the refs or image the model acted on."""
        if tab is None:
            tab = self.tab
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
        self, *, ref: str, tab: Tab | None = None, scroll: bool = True
    ) -> ElementPoint:
        """Reveal a ref and return a hit-tested point with an action-scoped aim."""
        action = self._invocation.context.current
        if tab is None:
            tab = self.tab
        if action is not None and not action.started:
            await self._runner.start(action)
        targeting = self._mount.targeting
        assert targeting is not None
        return await targeting.locate(
            tab=tab, ref=ref, scroll=scroll, report=self._record_preparation
        )

    @property
    def tab(self) -> Tab:
        """The fixed addressed tab of the browser tool currently executing."""
        return self._invocation.context.tab

    @hook(ExecuteTool, ReviewToolResult)
    async def _execute_browser_result(
        self, event: ExecuteTool | ReviewToolResult, next_: Next[ToolResult]
    ) -> ToolResult:
        # Set the signal before the execution receipt is persisted, including on errors.
        return stop_on_failure(await next_(), event.tool)

    @hook(BrowserToolCall)
    async def _run_tool(self, event: BrowserToolCall, next_: Next[object]) -> object:
        return await self._invocation.run(event, next_)

    def _record_preparation(self, note: str) -> None:
        action = self._invocation.context.current
        if action is None:
            return
        if len(action.preparation_notes) < 8:
            action.preparation_notes.append(note)
        else:
            action.preparation_omitted += 1

    @property
    def _runner(self) -> ActionRunner:
        runner = self._mount.runner
        assert runner is not None
        return runner

    @property
    def _invocation(self) -> ToolExecution:
        invocation = self._mount.invocation
        assert invocation is not None
        return invocation
