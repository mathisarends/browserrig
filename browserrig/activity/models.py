from collections.abc import Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Self, assert_never

from harnessed.events import SessionEvent, step, turn
from pydantic import model_validator

from browserrig.browser.config import Options
from browserrig.events import ActivityFinishedEvent, ActivityStartedEvent
from browserrig.kinds import ActivityKind, ActivityOutcome


@dataclass(frozen=True, slots=True)
class ActivityKey:
    """Singleton model/pause slots and separately correlated tool/readiness slots."""

    kind: ActivityKind
    correlation_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind(self.kind))
        if not isinstance(self.correlation_id, str):
            raise TypeError("Activity correlation IDs must be strings")
        correlated = self.kind in {ActivityKind.TOOL, ActivityKind.READINESS}
        if bool(self.correlation_id) != correlated:
            raise ValueError("Only tool and readiness activities require a correlation ID")


def step_outcome(reason: step.Outcome) -> ActivityOutcome:
    match reason:
        case step.Outcome.COMPLETED:
            return ActivityOutcome.COMPLETED
        case step.Outcome.INTERRUPTED:
            return ActivityOutcome.INTERRUPTED
        case step.Outcome.ABORTED:
            return ActivityOutcome.ABORTED
        case step.Outcome.CONTEXT_LIMIT:
            return ActivityOutcome.CONTEXT_LIMIT
        case _:
            assert_never(reason)


def turn_outcome(reason: turn.Outcome) -> ActivityOutcome:
    match reason:
        case turn.Outcome.COMPLETED:
            outcome = ActivityOutcome.COMPLETED
        case turn.Outcome.INTERRUPTED:
            outcome = ActivityOutcome.INTERRUPTED
        case turn.Outcome.STOPPED:
            outcome = ActivityOutcome.STOPPED
        case turn.Outcome.MAX_STEPS:
            outcome = ActivityOutcome.MAX_STEPS
        case turn.Outcome.TOKEN_BUDGET:
            outcome = ActivityOutcome.TOKEN_BUDGET
        case turn.Outcome.REJECTED:
            outcome = ActivityOutcome.REJECTED
        case turn.Outcome.ABORTED:
            outcome = ActivityOutcome.ABORTED
        case turn.Outcome.DISCARDED:
            outcome = ActivityOutcome.DISCARDED
        case _:
            assert_never(reason)
    return outcome


class TimeRange(Options):
    start: float
    end: float

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("Interval end precedes start")
        return self


def project_intervals(
    records: Iterable[SessionEvent], *, now: float | None = None
) -> tuple[ActivityFinishedEvent, ...]:
    """Read live or restored facts without depending on a mounted Activity instance."""
    completed: list[ActivityFinishedEvent] = []
    opened: dict[str, ActivityStartedEvent] = {}
    for record in records:
        match record:
            case ActivityStartedEvent(interval_id=interval_id):
                opened[interval_id] = record
            case ActivityFinishedEvent(interval_id=interval_id):
                completed.append(record)
                opened.pop(interval_id, None)
    timestamp = monotonic() if now is None else now
    completed.extend(
        ActivityFinishedEvent(
            interval_id=event.interval_id,
            kind=event.kind,
            cause_id=event.cause_id,
            started_at=event.at,
            at=timestamp,
            outcome=ActivityOutcome.RUNNING,
            epoch_id=event.epoch_id,
        )
        for event in opened.values()
    )
    return tuple(completed)


def inference_only(intervals: tuple[ActivityFinishedEvent, ...]) -> tuple[TimeRange, ...]:
    """Subtract overlapping tool/readiness/pause time from client-side model waits."""
    result: list[TimeRange] = []
    for interval in intervals:
        if interval.kind != ActivityKind.LLM:
            continue
        cursor = interval.started_at
        blockers = sorted(
            (
                item
                for item in intervals
                if item.kind != ActivityKind.LLM
                and item.epoch_id == interval.epoch_id
                and item.at > cursor
                and item.started_at < interval.at
            ),
            key=lambda item: item.started_at,
        )
        for blocker in blockers:
            if blocker.started_at > cursor:
                result.append(TimeRange(start=cursor, end=min(blocker.started_at, interval.at)))
            cursor = max(cursor, blocker.at)
            if cursor >= interval.at:
                break
        if cursor < interval.at:
            result.append(TimeRange(start=cursor, end=interval.at))
    return tuple(result)
