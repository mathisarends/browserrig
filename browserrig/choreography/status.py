"""Project status facts into what viewers show: downloads, uploads and activities."""

from dataclasses import replace

from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    BrowserEvent,
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
    FilesUploadedEvent,
)

from .events import (
    ActivityPresentedEvent,
    DownloadPresentedEvent,
    PresentedEvent,
    UploadPresentedEvent,
    WorkPhase,
)
from .work import clipped

type StatusFact = BrowserEvent | DownloadProgressedEvent


class StatusProjection:
    """Remember what each running download is called, so every receipt names it."""

    def __init__(self) -> None:
        self._filenames: dict[str, str] = {}

    def project(self, event: StatusFact) -> PresentedEvent | None:
        """Return the receipt for a status fact, or None for any other event."""
        presented = self._project(event)
        return (
            replace(presented, target_id=event.target_id, document_id=event.document_id)
            if presented
            else None
        )

    def _project(self, event: StatusFact) -> PresentedEvent | None:
        match event:
            case ActivityStartedEvent() | ActivityFinishedEvent():
                return ActivityPresentedEvent(
                    interval_id=event.interval_id,
                    kind=event.kind,
                    active=isinstance(event, ActivityStartedEvent),
                )
            case DownloadStartedEvent():
                self._filenames[event.download_id] = event.filename
                return DownloadPresentedEvent(
                    download_id=event.download_id,
                    filename=event.filename,
                    phase=WorkPhase.RUNNING,
                )
            case DownloadProgressedEvent():
                return DownloadPresentedEvent(
                    download_id=event.download_id,
                    filename=self._filenames.get(event.download_id, ""),
                    phase=WorkPhase.RUNNING,
                    received_bytes=event.received_bytes,
                    total_bytes=event.total_bytes,
                )
            case (
                DownloadCompletedEvent()
                | DownloadFailedEvent()
                | DownloadCanceledEvent()
            ):
                return self._finished(event)
            case FilesUploadedEvent():
                return UploadPresentedEvent(paths=event.paths, ref=event.ref)
            case _:
                return None

    def _finished(
        self,
        event: DownloadCompletedEvent | DownloadFailedEvent | DownloadCanceledEvent,
    ) -> DownloadPresentedEvent:
        filename = self._filenames.pop(event.download_id, "")
        match event:
            case DownloadCompletedEvent():
                return DownloadPresentedEvent(
                    download_id=event.download_id,
                    filename=event.filename or filename,
                    phase=WorkPhase.COMPLETED,
                    received_bytes=event.size,
                    total_bytes=event.size,
                )
            case DownloadFailedEvent():
                return DownloadPresentedEvent(
                    download_id=event.download_id,
                    filename=filename,
                    phase=WorkPhase.FAILED,
                    reason=clipped(event.reason, 300),
                )
            case DownloadCanceledEvent():
                return DownloadPresentedEvent(
                    download_id=event.download_id,
                    filename=filename,
                    phase=WorkPhase.CANCELLED,
                )
