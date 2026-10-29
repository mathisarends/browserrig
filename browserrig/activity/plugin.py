from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from harnessed import Context, Inject, Plugin, PluginState, hook
from harnessed.core.session.session import SessionLog
from harnessed.events import message, model, session, step, tool, turn

from browserrig.events import (
    ACTIVITY_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    ReadinessEndedEvent,
    ReadinessStartedEvent,
)
from browserrig.kinds import ActivityKind


@dataclass
class _State:
    open: dict[str, ActivityStartedEvent] = field(default_factory=dict)
    log: SessionLog | None = None
    epoch: str = field(default_factory=lambda: uuid4().hex)
    request_count: int = 0


class Activity(Plugin):
    """Derive client-side inference and browser intervals from receipts, not wrappers."""

    events = ACTIVITY_EVENTS
    state = PluginState(_State)

    async def setup(self, ctx: Context, log: Inject[SessionLog]) -> None:
        self.state.log = log
        ctx.effect(self._close_all)
        ctx.provide(Activity, self)

    async def _start(self, key: str, kind: ActivityKind, cause: str) -> None:
        await self._finish(key, "superseded")
        event = ActivityStartedEvent(
            interval_id=uuid4().hex, kind=kind, cause_id=cause, epoch_id=self.state.epoch
        )
        self.state.open[key] = event
        assert self.state.log is not None
        await self.state.log.emit(event)

    async def _finish(self, key: str, outcome: str = "completed") -> None:
        event = self.state.open.pop(key, None)
        if event is not None:
            assert self.state.log is not None
            await self.state.log.emit(
                ActivityFinishedEvent(
                    interval_id=event.interval_id,
                    kind=event.kind,
                    cause_id=event.cause_id,
                    started_at=event.at,
                    outcome=outcome,
                    epoch_id=event.epoch_id,
                )
            )

    async def _close_all(self) -> None:
        for key in tuple(self.state.open):
            await self._finish(key, "closed")

    @hook(model.Requested)
    async def on_model(self, event: model.Requested) -> None:
        self.state.request_count += 1
        await self._start("llm", ActivityKind.LLM, f"{self.state.epoch}:{self.state.request_count}")

    @hook(message.Assistant)
    async def on_assistant(self, event: message.Assistant) -> None:
        await self._finish("llm", "interrupted" if event.interrupted else "completed")

    @hook(tool.ExecutionStarted)
    async def on_tool(self, event: tool.ExecutionStarted) -> None:
        await self._finish("llm")
        await self._start(f"tool:{event.call_id}", ActivityKind.TOOL, event.call_id)

    @hook(tool.ExecutionFinished)
    async def on_tool_finished(self, event: tool.ExecutionFinished) -> None:
        await self._finish(f"tool:{event.call_id}")

    @hook(ReadinessStartedEvent)
    async def on_readiness(self, event: ReadinessStartedEvent) -> None:
        await self._start(event.readiness_id, ActivityKind.READINESS, event.readiness_id)

    @hook(ReadinessEndedEvent)
    async def on_ready(self, event: ReadinessEndedEvent) -> None:
        await self._finish(event.readiness_id, event.reason or "completed")

    @hook(session.ControlChanged)
    async def on_control(self, event: session.ControlChanged) -> None:
        if event.state == session.ControlState.PAUSED:
            await self._start("paused", ActivityKind.PAUSED, self.state.epoch)
        elif event.state == session.ControlState.ACTIVE:
            await self._finish("paused")

    @hook(step.Finished)
    async def on_step(self, event: step.Finished) -> None:
        await self._finish("llm", str(event.reason))

    @hook(turn.Ended)
    async def on_turn(self, event: turn.Ended) -> None:
        for key in tuple(self.state.open):
            if key != "paused":
                await self._finish(key, str(event.reason))

    def intervals(self, *, now: float | None = None) -> tuple[ActivityFinishedEvent, ...]:
        assert self.state.log is not None
        closed = tuple(
            event
            for event in self.state.log.events
            if isinstance(event, ActivityFinishedEvent) and event.epoch_id == self.state.epoch
        )
        current_time = monotonic() if now is None else now
        running = tuple(
            ActivityFinishedEvent(
                interval_id=event.interval_id,
                kind=event.kind,
                cause_id=event.cause_id,
                started_at=event.at,
                outcome="running",
                at=current_time,
                epoch_id=event.epoch_id,
            )
            for event in self.state.open.values()
        )
        return closed + running
