"""Retain presentation receipts across document replacement.

Starts live until their matching terminal event; finished receipts live briefly.
Only the renderer serializes these events.
"""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import monotonic

from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    BrowserEvent,
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    EventKind,
    FilesUploadedEvent,
    LiveEvent,
)

from .events import WorkPhase, WorkPresentedEvent

type _Key = tuple[EventKind, str]


@dataclass(frozen=True, slots=True)
class _Receipt:
    event: BrowserEvent | LiveEvent
    expires_at: float | None


class Receipts:
    """A bounded cache indexed by the typed stream and operation identity."""

    def __init__(self) -> None:
        self._items: OrderedDict[_Key, _Receipt] = OrderedDict()

    def remember(self, event: BrowserEvent | LiveEvent) -> None:
        match event:
            case WorkPresentedEvent(work_id=identity, phase=phase):
                self._put(
                    EventKind.WORK_PRESENTED,
                    identity,
                    event,
                    running=phase is WorkPhase.RUNNING,
                    retention=event.retention,
                )
            case ActivityStartedEvent(interval_id=identity):
                self._put(EventKind.ACTIVITY_STARTED, identity, event, running=True)
            case ActivityFinishedEvent(interval_id=identity):
                self._items.pop((EventKind.ACTIVITY_STARTED, identity), None)
            case DownloadStartedEvent(download_id=identity):
                self._items.pop((EventKind.DOWNLOAD_PROGRESS, identity), None)
                self._put(EventKind.DOWNLOAD_STARTED, identity, event, running=True)
            case DownloadProgressedEvent(download_id=identity):
                self._put(EventKind.DOWNLOAD_PROGRESS, identity, event, running=True)
            case (
                DownloadCompletedEvent(download_id=identity)
                | DownloadFailedEvent(download_id=identity)
                | DownloadCanceledEvent(download_id=identity)
            ):
                self._items.pop((EventKind.DOWNLOAD_PROGRESS, identity), None)
                if started := self._items.get((EventKind.DOWNLOAD_STARTED, identity)):
                    self._put(
                        EventKind.DOWNLOAD_STARTED,
                        identity,
                        started.event,
                        retention=2.2,
                    )
                self._put(event.type, identity, event, retention=2.2)
            case FilesUploadedEvent():
                self._put(event.type, event.target_id, event)
        self._prune()

    def snapshot(self) -> tuple[BrowserEvent | LiveEvent, ...]:
        self._prune()
        now = monotonic()
        return tuple(
            replace(receipt.event, retention=max(0, receipt.expires_at - now))
            if isinstance(receipt.event, WorkPresentedEvent)
            and receipt.expires_at is not None
            else receipt.event
            for receipt in self._items.values()
        )

    def _put(
        self,
        stream: EventKind,
        identity: str,
        event: BrowserEvent | LiveEvent,
        *,
        running: bool = False,
        retention: float = 8,
    ) -> None:
        key = (stream, identity)
        self._items[key] = _Receipt(event, None if running else monotonic() + retention)
        self._items.move_to_end(key)

    def _prune(self) -> None:
        now = monotonic()
        for key, receipt in tuple(self._items.items()):
            if receipt.expires_at is not None and receipt.expires_at <= now:
                del self._items[key]
        while len(self._items) > 64:
            self._items.popitem(last=False)
