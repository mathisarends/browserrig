from dataclasses import dataclass, field
from typing import assert_never
from uuid import uuid4

from harnessed import Context, Inject, Plugin, PluginState, SessionLog, ToolStatus, hook
from harnessed.events import (
    AgentControlChangedEvent,
    AssistantMessageEvent,
    ControlState,
    ModelRequestedEvent,
    ModelRequestFailedEvent,
    ModelRequestOutcome,
    StepEndedEvent,
    ToolExecutionFinishedEvent,
    ToolExecutionStartedEvent,
    TurnEndedEvent,
)

from browserrig.events import (
    ACTIVITY_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessEndedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)
from browserrig.kinds import ActivityKind, ActivityOutcome

from .models import ActivityKey, project_intervals, step_outcome, turn_outcome

_PAUSE = ActivityKey(ActivityKind.PAUSED)


@dataclass
class _State:
    open: dict[ActivityKey, ActivityStartedEvent] = field(default_factory=dict)
    epoch: str = field(default_factory=lambda: uuid4().hex)


class Activity(Plugin, provides=True):
    """Derive client-side inference and browser intervals from receipts, not wrappers."""

    events = ACTIVITY_EVENTS
    state = PluginState(_State)
    log: Inject[SessionLog]

    async def setup(self, ctx: Context) -> None:
        ctx.effect(self._close_all)

    async def _start(self, key: ActivityKey, *, cause_id: str) -> None:
        """A new interval in the same slot supersedes only that slot's previous interval."""
        await self._finish(key, ActivityOutcome.SUPERSEDED)
        event = ActivityStartedEvent(
            interval_id=uuid4().hex, kind=key.kind, cause_id=cause_id, epoch_id=self.state.epoch
        )
        self.state.open[key] = event
        await self.log.emit(event)

    async def _finish(
        self,
        key: ActivityKey,
        outcome: ActivityOutcome = ActivityOutcome.COMPLETED,
        *,
        reason: str = "",
    ) -> None:
        event = self.state.open.pop(key, None)
        if event is None:
            return
        await self.log.emit(
            ActivityFinishedEvent(
                interval_id=event.interval_id,
                kind=event.kind,
                cause_id=event.cause_id,
                started_at=event.at,
                outcome=outcome,
                reason=reason,
                epoch_id=event.epoch_id,
            )
        )

    async def _close_all(self) -> None:
        for key in tuple(self.state.open):
            await self._finish(key, ActivityOutcome.CLOSED)

    @hook(ModelRequestedEvent)
    async def on_model(self, event: ModelRequestedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.LLM, event.request_id), cause_id=event.request_id
        )

    @hook(AssistantMessageEvent)
    async def on_assistant(self, event: AssistantMessageEvent) -> None:
        await self._finish(
            ActivityKey(ActivityKind.LLM, event.request_id),
            ActivityOutcome.INTERRUPTED if event.interrupted else ActivityOutcome.COMPLETED,
        )

    @hook(ModelRequestFailedEvent)
    async def on_model_failed(self, event: ModelRequestFailedEvent) -> None:
        match event.outcome:
            case ModelRequestOutcome.FAILED:
                outcome = ActivityOutcome.FAILED
            case ModelRequestOutcome.CANCELLED:
                outcome = ActivityOutcome.CANCELLED
            case ModelRequestOutcome.CONTEXT_EXCEEDED:
                outcome = ActivityOutcome.CONTEXT_LIMIT
            case _:
                assert_never(event.outcome)
        await self._finish(
            ActivityKey(ActivityKind.LLM, event.request_id), outcome, reason=event.outcome.value
        )

    @hook(ToolExecutionStartedEvent)
    async def on_tool(self, event: ToolExecutionStartedEvent) -> None:
        await self._start(ActivityKey(ActivityKind.TOOL, event.call_id), cause_id=event.call_id)

    @hook(ToolExecutionFinishedEvent)
    async def on_tool_finished(self, event: ToolExecutionFinishedEvent) -> None:
        reason = event.result.status.value if event.result.is_error else ""
        if event.result.exit_code not in (None, 0):
            reason = f"{event.result.status.value}; exit_code={event.result.exit_code}"
        if event.result.status is ToolStatus.CANCELLED:
            outcome = ActivityOutcome.CANCELLED
        elif event.result.status is ToolStatus.TIMEOUT:
            outcome = ActivityOutcome.TIMEOUT
        else:
            outcome = ActivityOutcome.FAILED if event.result.is_error else ActivityOutcome.COMPLETED
        await self._finish(
            ActivityKey(ActivityKind.TOOL, event.call_id),
            outcome,
            reason=reason,
        )

    @hook(ReadinessStartedEvent)
    async def on_readiness(self, event: ReadinessStartedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.READINESS, event.readiness_id), cause_id=event.readiness_id
        )

    @hook(ReadinessEndedEvent)
    async def on_ready(self, event: ReadinessEndedEvent) -> None:
        match event:
            case ReadyEvent():
                outcome = ActivityOutcome.COMPLETED
            case ReadinessDegradedEvent():
                outcome = ActivityOutcome.DEGRADED
            case ReadinessFailedEvent():
                outcome = ActivityOutcome.FAILED
            case ReadinessCancelledEvent():
                outcome = ActivityOutcome.CANCELLED
            case _:
                raise TypeError(f"Unsupported readiness event: {type(event).__name__}")
        await self._finish(
            ActivityKey(ActivityKind.READINESS, event.readiness_id), outcome, reason=event.reason
        )

    @hook(AgentControlChangedEvent)
    async def on_control(self, event: AgentControlChangedEvent) -> None:
        if event.state == ControlState.PAUSED:
            await self._start(_PAUSE, cause_id=self.state.epoch)
        elif event.state == ControlState.ACTIVE:
            await self._finish(_PAUSE)

    @hook(StepEndedEvent)
    async def on_step(self, event: StepEndedEvent) -> None:
        for key in tuple(self.state.open):
            if key.kind is ActivityKind.LLM:
                await self._finish(key, step_outcome(event.reason))

    @hook(TurnEndedEvent)
    async def on_turn(self, event: TurnEndedEvent) -> None:
        for key in tuple(self.state.open):
            if key.kind != ActivityKind.PAUSED:
                await self._finish(key, turn_outcome(event.reason))

    def intervals(self, *, now: float | None = None) -> tuple[ActivityFinishedEvent, ...]:
        return project_intervals(
            (
                event
                for event in self.log.events
                if isinstance(event, ActivityStartedEvent | ActivityFinishedEvent)
                and event.epoch_id == self.state.epoch
            ),
            now=now,
        )
