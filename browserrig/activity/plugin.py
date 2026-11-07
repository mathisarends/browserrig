from typing import assert_never
from uuid import uuid4

from harnessed import Plugin, PluginState, SessionLog, ToolStatus, hook
from harnessed.events import (
    AssistantMessageEvent,
    CompactionFinishedEvent,
    CompactionOutcome,
    CompactionStartedEvent,
    ControlState,
    ModelRequestedEvent,
    ModelRequestFailedEvent,
    ModelRequestOutcome,
    SessionControlChangedEvent,
    StepEndedEvent,
    ToolExecutionFinishedEvent,
    ToolExecutionStartedEvent,
    TurnEndedEvent,
)
from harnessed.kernel import Scope, needs

from browserrig.core import ActivityKind, ActivityOutcome
from browserrig.events import (
    ACTIVITY_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    HandoffFinishedEvent,
    HandoffRequestedEvent,
    ReadinessCancelledEvent,
    ReadinessDegradedEvent,
    ReadinessEndedEvent,
    ReadinessFailedEvent,
    ReadinessStartedEvent,
    ReadyEvent,
)

from .models import ActivityKey, project_intervals, step_outcome, turn_outcome
from .state import ActivityState

_PAUSE = ActivityKey(ActivityKind.PAUSED)


class Activity(Plugin, slot="browserrig.activity", provides=True):
    events = ACTIVITY_EVENTS
    _state = PluginState(ActivityState)
    _log = needs(SessionLog)

    async def setup(self, ctx: Scope) -> None:
        ctx.effect(self._close_all)

    def intervals(
        self, *, now: float | None = None
    ) -> tuple[ActivityFinishedEvent, ...]:
        return project_intervals(self._state.records, now=now)

    async def _start(self, key: ActivityKey, *, cause_id: str) -> None:
        """A new interval in the same slot supersedes only that slot's previous interval."""
        await self._finish(key, ActivityOutcome.SUPERSEDED)
        event = ActivityStartedEvent(
            interval_id=uuid4().hex,
            kind=key.kind,
            cause_id=cause_id,
            epoch_id=self._state.epoch,
        )
        self._state.open[key] = event
        self._state.records.append(event)
        await self._log.emit(event)

    async def _finish(
        self,
        key: ActivityKey,
        outcome: ActivityOutcome = ActivityOutcome.COMPLETED,
        *,
        reason: str = "",
    ) -> None:
        event = self._state.open.pop(key, None)
        if event is None:
            return
        finished = ActivityFinishedEvent(
            interval_id=event.interval_id,
            kind=event.kind,
            cause_id=event.cause_id,
            started_at=event.at,
            outcome=outcome,
            reason=reason,
            epoch_id=event.epoch_id,
        )
        self._state.records.append(finished)
        await self._log.emit(finished)

    async def _close_all(self) -> None:
        for key in tuple(self._state.open):
            await self._finish(key, ActivityOutcome.CLOSED)

    @hook(ModelRequestedEvent)
    async def _on_model(self, event: ModelRequestedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.LLM, event.request_id), cause_id=event.request_id
        )

    @hook(AssistantMessageEvent)
    async def _on_assistant(self, event: AssistantMessageEvent) -> None:
        await self._finish(
            ActivityKey(ActivityKind.LLM, event.request_id),
            ActivityOutcome.INTERRUPTED
            if event.interrupted
            else ActivityOutcome.COMPLETED,
        )

    @hook(ModelRequestFailedEvent)
    async def _on_model_failed(self, event: ModelRequestFailedEvent) -> None:
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
            ActivityKey(ActivityKind.LLM, event.request_id),
            outcome,
            reason=event.outcome.value,
        )

    @hook(CompactionStartedEvent)
    async def _on_compaction(self, event: CompactionStartedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.COMPACTION, event.compaction_id),
            cause_id=event.compaction_id,
        )

    @hook(CompactionFinishedEvent)
    async def _on_compaction_finished(self, event: CompactionFinishedEvent) -> None:
        outcome = {
            CompactionOutcome.APPLIED: ActivityOutcome.COMPLETED,
            CompactionOutcome.DISCARDED: ActivityOutcome.DISCARDED,
            CompactionOutcome.FAILED: ActivityOutcome.FAILED,
            CompactionOutcome.CANCELLED: ActivityOutcome.CANCELLED,
        }[event.outcome]
        await self._finish(
            ActivityKey(ActivityKind.COMPACTION, event.compaction_id),
            outcome,
            reason=event.outcome.value,
        )

    @hook(ToolExecutionStartedEvent)
    async def _on_tool(self, event: ToolExecutionStartedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.TOOL, event.call_id), cause_id=event.call_id
        )

    @hook(ToolExecutionFinishedEvent)
    async def _on_tool_finished(self, event: ToolExecutionFinishedEvent) -> None:
        reason = event.result.status.value if event.result.is_error else ""
        if event.result.exit_code not in (None, 0):
            reason = f"{event.result.status.value}; exit_code={event.result.exit_code}"
        if event.result.status is ToolStatus.CANCELLED:
            outcome = ActivityOutcome.CANCELLED
        elif event.result.status is ToolStatus.TIMEOUT:
            outcome = ActivityOutcome.TIMEOUT
        else:
            outcome = (
                ActivityOutcome.FAILED
                if event.result.is_error
                else ActivityOutcome.COMPLETED
            )
        await self._finish(
            ActivityKey(ActivityKind.TOOL, event.call_id),
            outcome,
            reason=reason,
        )

    @hook(HandoffRequestedEvent)
    async def _on_handoff(self, event: HandoffRequestedEvent) -> None:
        if event.call_id:
            await self._finish(ActivityKey(ActivityKind.TOOL, event.call_id))
            await self._start(
                ActivityKey(ActivityKind.HANDOFF, event.handoff_id),
                cause_id=event.handoff_id,
            )

    @hook(HandoffFinishedEvent)
    async def _on_handoff_finished(self, event: HandoffFinishedEvent) -> None:
        if event.call_id:
            outcome = {
                "done": ActivityOutcome.COMPLETED,
                "declined": ActivityOutcome.REJECTED,
                "timeout": ActivityOutcome.TIMEOUT,
                "cancelled": ActivityOutcome.CANCELLED,
                "failed": ActivityOutcome.FAILED,
                "resumed": ActivityOutcome.COMPLETED,
            }[event.status]
            await self._finish(
                ActivityKey(ActivityKind.HANDOFF, event.handoff_id),
                outcome,
                reason=event.status,
            )
            await self._start(
                ActivityKey(ActivityKind.TOOL, event.call_id), cause_id=event.call_id
            )

    @hook(ReadinessStartedEvent)
    async def _on_readiness(self, event: ReadinessStartedEvent) -> None:
        await self._start(
            ActivityKey(ActivityKind.READINESS, event.readiness_id),
            cause_id=event.readiness_id,
        )

    @hook(ReadinessEndedEvent)
    async def _on_ready(self, event: ReadinessEndedEvent) -> None:
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
            ActivityKey(ActivityKind.READINESS, event.readiness_id),
            outcome,
            reason=event.reason,
        )

    @hook(SessionControlChangedEvent)
    async def _on_control(self, event: SessionControlChangedEvent) -> None:
        if event.state == ControlState.PAUSED:
            await self._start(_PAUSE, cause_id=self._state.epoch)
        elif event.state == ControlState.ACTIVE:
            await self._finish(_PAUSE)

    @hook(StepEndedEvent)
    async def _on_step(self, event: StepEndedEvent) -> None:
        for key in tuple(self._state.open):
            if key.kind is ActivityKind.LLM:
                await self._finish(key, step_outcome(event.reason))

    @hook(TurnEndedEvent)
    async def _on_turn(self, event: TurnEndedEvent) -> None:
        for key in tuple(self._state.open):
            if key.kind != ActivityKind.PAUSED:
                await self._finish(key, turn_outcome(event.reason))
