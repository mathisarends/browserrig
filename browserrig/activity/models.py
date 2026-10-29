from collections.abc import Iterable
from time import monotonic
from typing import Self

from harnessed.events import SessionEvent
from pydantic import model_validator

from browserrig.browser.config import Options
from browserrig.events import ActivityFinishedEvent, ActivityStartedEvent
from browserrig.kinds import ActivityKind


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
            outcome="running",
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
