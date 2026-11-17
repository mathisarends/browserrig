"""Retain presented receipts across document replacement.

Running receipts live until a later receipt replaces them; terminal receipts expire
after the `retention` their producer gave them. Only the overlay serializes these.
"""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import monotonic

from browserrig.choreography import (
    ActivityPresentedEvent,
    DownloadPresentedEvent,
    PresentedEvent,
    UploadPresentedEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.events import EventKind

type _Key = tuple[EventKind, str]
type _Expiring = WorkPresentedEvent | DownloadPresentedEvent | UploadPresentedEvent


@dataclass(frozen=True, slots=True)
class _Receipt:
    event: PresentedEvent
    expires_at: float | None

    def event_at(self, now: float) -> PresentedEvent:
        if (
            isinstance(
                self.event,
                (WorkPresentedEvent, DownloadPresentedEvent, UploadPresentedEvent),
            )
            and self.expires_at is not None
        ):
            return replace(self.event, retention=max(0, self.expires_at - now))
        return self.event


class Receipts:
    """A bounded cache indexed by receipt type and operation identity."""

    def __init__(self) -> None:
        self._items: OrderedDict[_Key, _Receipt] = OrderedDict()

    def remember(self, event: PresentedEvent) -> None:
        match event:
            case WorkPresentedEvent(work_id=identity, phase=phase) | (
                DownloadPresentedEvent(download_id=identity, phase=phase)
            ):
                self._put(event, identity, running=phase is WorkPhase.RUNNING)
            case UploadPresentedEvent():
                self._put(event, event.target_id, running=False)
            case ActivityPresentedEvent(interval_id=identity, active=True):
                self._items[event.type, identity] = _Receipt(event, None)
                self._items.move_to_end((event.type, identity))
            case ActivityPresentedEvent(interval_id=identity):
                self._items.pop((event.type, identity), None)
        self._prune()

    def snapshot(self) -> tuple[PresentedEvent, ...]:
        self._prune()
        now = monotonic()
        return tuple(receipt.event_at(now) for receipt in self._items.values())

    def _put(self, event: _Expiring, identity: str, *, running: bool) -> None:
        key = (event.type, identity)
        expires_at = None if running else monotonic() + event.retention
        self._items[key] = _Receipt(event, expires_at)
        self._items.move_to_end(key)

    def _prune(self) -> None:
        now = monotonic()
        for key, receipt in tuple(self._items.items()):
            if receipt.expires_at is not None and receipt.expires_at <= now:
                del self._items[key]
        while len(self._items) > 64:
            self._items.popitem(last=False)
