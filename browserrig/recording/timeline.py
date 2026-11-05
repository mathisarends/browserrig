from collections.abc import Iterable

from browserrig.core import ActivityKind
from browserrig.events import ActivityFinishedEvent

from .models import Span

_INACTIVE = {ActivityKind.LLM, ActivityKind.COMPACTION, ActivityKind.PAUSED}


def kept_spans(
    intervals: Iterable[ActivityFinishedEvent],
    *,
    started_at: float,
    ended_at: float,
    padding: float,
) -> tuple[Span, ...]:
    """Cut inactive time, retaining concurrent work and context around each cut.

    Activity uses the same process monotonic clock as the recording. Merge idle
    intervals before applying padding, so overlapping LLM/compaction waits do not
    leave islands of waiting time in the video.
    """
    intervals = tuple(intervals)
    inactive = _merge(
        Span(max(started_at, item.started_at), min(ended_at, item.at))
        for item in intervals
        if item.kind in _INACTIVE
    )
    active = _merge(
        Span(max(started_at, item.started_at), min(ended_at, item.at))
        for item in intervals
        if item.kind not in _INACTIVE
    )
    cuts = []
    for span in inactive:
        cursor = span.start + padding
        end = span.end - padding
        for work in active:
            if work.end <= cursor or work.start >= end:
                continue
            if work.start - padding > cursor:
                cuts.append(Span(cursor, work.start - padding))
            cursor = max(cursor, work.end + padding)
        if end > cursor:
            cuts.append(Span(cursor, end))
    kept = []
    cursor = started_at
    for cut in _merge(cuts):
        if cut.start > cursor:
            kept.append(Span(cursor - started_at, cut.start - started_at))
        cursor = max(cursor, cut.end)
    if ended_at > cursor:
        kept.append(Span(cursor - started_at, ended_at - started_at))
    return tuple(kept)


def _merge(spans: Iterable[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in sorted(spans, key=lambda item: item.start):
        if span.end <= span.start:
            continue
        if merged and span.start <= merged[-1].end:
            merged[-1] = Span(merged[-1].start, max(merged[-1].end, span.end))
        else:
            merged.append(span)
    return merged
