from collections.abc import Iterable
from dataclasses import dataclass
from time import monotonic
from typing import assert_never

from harnessed.events import SessionEvent, StepOutcome, TurnOutcome

from browserrig.core.kinds import ActivityKind, ActivityOutcome
from browserrig.events import ActivityFinishedEvent, ActivityStartedEvent


@dataclass(frozen=True, slots=True)
class ActivityKey:
    """Correlated request/tool/readiness slots and a singleton pause slot."""

    kind: ActivityKind
    correlation_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActivityKind(self.kind))
        if not isinstance(self.correlation_id, str):
            raise TypeError("Activity correlation IDs must be strings")
        correlated = self.kind != ActivityKind.PAUSED
        if bool(self.correlation_id) != correlated:
            raise ValueError(
                "Model, tool, readiness and compaction activities require a correlation ID"
            )


def step_outcome(reason: StepOutcome) -> ActivityOutcome:
    match reason:
        case StepOutcome.COMPLETED:
            return ActivityOutcome.COMPLETED
        case StepOutcome.INTERRUPTED:
            return ActivityOutcome.INTERRUPTED
        case StepOutcome.ABORTED:
            return ActivityOutcome.ABORTED
        case StepOutcome.CONTEXT_LIMIT:
            return ActivityOutcome.CONTEXT_LIMIT
        case _:
            assert_never(reason)


def turn_outcome(reason: TurnOutcome) -> ActivityOutcome:
    match reason:
        case TurnOutcome.COMPLETED:
            outcome = ActivityOutcome.COMPLETED
        case TurnOutcome.INTERRUPTED:
            outcome = ActivityOutcome.INTERRUPTED
        case TurnOutcome.STOPPED:
            outcome = ActivityOutcome.STOPPED
        case TurnOutcome.MAX_STEPS:
            outcome = ActivityOutcome.MAX_STEPS
        case TurnOutcome.TOKEN_BUDGET:
            outcome = ActivityOutcome.TOKEN_BUDGET
        case TurnOutcome.REJECTED:
            outcome = ActivityOutcome.REJECTED
        case TurnOutcome.ABORTED:
            outcome = ActivityOutcome.ABORTED
        case TurnOutcome.DISCARDED:
            outcome = ActivityOutcome.DISCARDED
        case _:
            assert_never(reason)
    return outcome


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
