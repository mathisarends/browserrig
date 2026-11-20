from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import cast

from harnessed import Plugin, SystemPrompt
from harnessed.hooks import ExecuteTool, Next, ReviewToolResult
from harnessed.kernel import PluginScope, PluginState, hook, needs, observes
from harnessed.models import ToolResult
from harnessed.prompts import Instructions
from harnessed.tracing import record, traced

from browserrig.browser import (
    AppState,
    Browser,
    BrowserEvents,
    Tab,
    blocked_reason,
    read_generation,
)
from browserrig.core import (
    ActionContext,
    ActionKind,
    ActionLabel,
    BrowserCoordination,
    BrowserError,
    BrowserToolCall,
)
from browserrig.events import ACTION_EVENTS
from browserrig.observation import (
    BrowserPerception,
    check_coordinates,
    check_observation,
)
from browserrig.readiness import PageReadiness
from browserrig.secrets import Secrets
from browserrig.tools.chains import (
    ActionChainPolicy,
    ObserveAfterInput,
    probe_change,
    stop_on_failure,
)
from browserrig.tools.effects import Effect
from browserrig.tools.intents import Intent, Perform

from .context import LABEL_CHARS
from .hooks import CheckAction
from .invocation import InvokeTool
from .policy import COORDINATE_KINDS, ActionProfile, action_profile
from .telemetry import Attribute, record_operation
from .transaction import ActionRunner


@dataclass
class _Mount:
    context: PluginScope | None = None
    runner: ActionRunner | None = None
    invocation: InvokeTool | None = None


class Actions(Plugin, slot="browserrig.actions", provides=True):
    """Expose browser action services and connect tool calls to their execution lifecycle."""

    events = ACTION_EVENTS
    _mount = PluginState(_Mount)
    _browser = needs(Browser)
    _actions = needs(ActionContext)
    _coordination = needs(BrowserCoordination)
    _events = needs(BrowserEvents)
    _readiness = needs(PageReadiness)
    _observe = needs(BrowserPerception)
    _app_state = observes(AppState)

    def __init__(self, *, chain_policy: ActionChainPolicy | None = None) -> None:
        super().__init__()
        self.chain_policy = (
            chain_policy if chain_policy is not None else ObserveAfterInput()
        )

    async def setup(self, scope: PluginScope) -> None:
        self._mount.context = scope
        self._mount.runner = ActionRunner(
            self._browser,
            self._coordination,
            self._events,
            self._readiness,
            self._observe,
            actions=self._actions,
            page_change=self.page_change,
            check_action=self._check_action,
            scope=scope,
            redact=self._redact_trace,
        )
        self._mount.invocation = InvokeTool(self._runner, self._coordination)

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
        label: str = "",
    ) -> ToolResult:
        """Run an explicitly managed operation outside an automatically wrapped tool."""
        record(kind=kind)
        call = self._invocation.context.call
        if label:
            call = replace(call, label=label[:LABEL_CHARS])
        return await self._runner.run(
            kind=kind,
            operation=operation,
            check=check,
            expects_change=expects_change,
            settle=settle,
            call=call,
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
        performed = Perform(intent, tab, self._actions.action_id)
        dispatched = await context.dispatch(performed, default=step)
        return cast(R, dispatched)

    @traced
    async def page_change(
        self, tab: Tab | None = None, *, after_input: bool = True
    ) -> str:
        """A comparison probe must never replace the refs or image the model acted on."""
        if tab is None:
            tab = self.tab
        if tab.closed or self._browser.active_tab.id != tab.id:
            return "The active tab changed."
        try:
            if not after_input:
                return await probe_change(self._observe, tab)
            return await self.chain_policy.check(self._observe, tab)
        except Exception:  # pylint: disable=broad-exception-caught
            # Successful input remains successful even if comparison fails.
            return "The page could not be checked after input."

    async def begin_preparation(self) -> None:
        """Mark an executing action as started before target preparation has effects."""
        action = self._invocation.context.current
        if action is not None and not action.started:
            await self._runner.start(action)

    def record_preparation(self, note: str) -> None:
        """Include bounded target-preparation diagnostics in the action receipt."""
        action = self._invocation.context.current
        if action is None:
            return
        if len(action.preparation_notes) < 8:
            action.preparation_notes.append(note)
        else:
            action.preparation_omitted += 1

    def record_receipt(self, **attributes: Attribute) -> None:
        """Add extension attributes to the current managed action's operation span."""
        for key, value in attributes.items():
            redacted = self._redact_trace(value) if isinstance(value, str) else value
            record_operation(**{f"receipt.{key}": redacted})

    @property
    def tab(self) -> Tab:
        """The fixed addressed tab of the browser tool currently executing."""
        return self._invocation.context.tab

    @hook(ExecuteTool)
    async def _bind_call(
        self, event: ExecuteTool, next_: Next[ToolResult]
    ) -> ToolResult:
        label = event.envelope.get(ActionLabel)
        text = label.action_label if label is not None else event.call.name
        context = self._mount.context
        if context is not None and Secrets in context:
            text = context[Secrets].redact(text)
        with self._invocation.context.bind_call(event.call.id, text, event.call.name):
            return await next_()

    @hook(ExecuteTool, ReviewToolResult)
    async def _execute_browser_result(
        self, event: ExecuteTool | ReviewToolResult, next_: Next[ToolResult]
    ) -> ToolResult:
        # Set the signal before the execution receipt is persisted, including on errors.
        result = await next_()
        return stop_on_failure(result, event.tool)

    @hook(BrowserToolCall)
    async def _run_tool(self, event: BrowserToolCall, next_: Next[object]) -> object:
        return await self._invocation(event, next_)

    async def _check_action(self, tab: Tab, kind: ActionKind) -> None:
        profile = action_profile(kind) or ActionProfile()
        app_state = self._app_state
        if (profile.phase is not None or app_state is not None) and (
            reason := await blocked_reason(tab, app_state)
        ) is not None:
            raise BrowserError(reason)
        observation = self._observe.snapshot
        coordinates = self._observe.coordinates
        if profile.requires_observation:
            current = await read_generation(tab, app_state)
            check_observation(
                tab,
                current,
                observation,
                reason=(
                    "The observed tab or document changed; act on the next observation"
                    if app_state is None
                    else "The observed page state changed; act on the next observation"
                ),
            )
            if kind in COORDINATE_KINDS:
                check_coordinates(tab, current, observation, coordinates)
        context = self._mount.context
        assert context is not None
        await context.dispatch(CheckAction(tab, kind, observation, coordinates))

    def _redact_trace(self, value: str) -> str:
        context = self._mount.context
        return (
            context[Secrets].redact(value)
            if context is not None and Secrets in context
            else value
        )

    @property
    def _runner(self) -> ActionRunner:
        runner = self._mount.runner
        assert runner is not None
        return runner

    @property
    def _invocation(self) -> InvokeTool:
        invocation = self._mount.invocation
        assert invocation is not None
        return invocation
