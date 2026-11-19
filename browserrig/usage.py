from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from harnessed import Plugin, hook
from harnessed.events import (
    DurableEvent,
    ModelUsageRecordedEvent,
    TransientEvent,
    TurnEndedEvent,
)
from harnessed.hooks import SessionAppended
from harnessed.models import ModelUsage
from harnessed.models.model import sum_usage

from .events import EventKind


@dataclass(frozen=True, slots=True)
class TurnUsageEvent(TransientEvent):
    """Model usage reported for a turn that has ended."""

    type: Literal[EventKind.TURN_USAGE] = field(
        default=EventKind.TURN_USAGE, kw_only=True
    )
    turn_id: str
    usage: ModelUsage


class TokenUsageTracker(Plugin):
    """Publish a TurnUsageEvent when Harnessed closes a turn."""

    events = (TurnUsageEvent,)

    @hook(SessionAppended)
    async def _appended(self, receipt: SessionAppended) -> None:
        if isinstance(receipt.event, TurnEndedEvent):
            usage = aggregate_model_usage(receipt.log.turns[-1].events)
            await receipt.log.publish(TurnUsageEvent(receipt.event.turn_id, usage))


def aggregate_model_usage(events: Iterable[DurableEvent]) -> ModelUsage:
    """Sum the provider usage captured in a turn's records."""
    return sum_usage(
        event.usage for event in events if isinstance(event, ModelUsageRecordedEvent)
    )
