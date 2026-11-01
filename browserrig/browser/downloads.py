from time import monotonic

from cdpify import CdpClient
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent

from browserrig.events import (
    DownloadCanceledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadProgressedEvent,
    DownloadStartedEvent,
)
from browserrig.files import Download, DownloadState, FileSystem

from .base import EventSink

# Chrome reports every received chunk; viewers only need a smooth progress ring.
_PROGRESS_INTERVAL_SECONDS = 0.2


class Downloads:
    """Track browser downloads and move completed files into the workspace."""

    def __init__(
        self, *, files: FileSystem | None, directory: str | None, emit: EventSink
    ) -> None:
        self._files = files
        self._directory = directory
        self._emit = emit
        self._items: dict[str, Download] = {}
        self._progress_at: dict[str, float] = {}

    async def enable(self, client: CdpClient, context_id: str | None) -> None:
        directory = (
            str(self._files.pending_directory) if self._files else self._directory
        )
        if directory is not None:
            await client.browser.set_download_behavior(
                behavior="allowAndName",
                download_path=directory,
                browser_context_id=context_id,
                events_enabled=True,
            )

    def all(self) -> tuple[Download, ...]:
        return tuple(self._items.values())

    async def handle(
        self, event: DownloadWillBeginEvent | DownloadProgressEvent
    ) -> None:
        match event:
            case DownloadWillBeginEvent():
                self._items[event.guid] = Download(
                    id=event.guid, url=event.url, filename=event.suggested_filename
                )
                await self._emit(
                    DownloadStartedEvent(
                        download_id=event.guid,
                        filename=event.suggested_filename,
                        url=event.url,
                    )
                )
            case DownloadProgressEvent() if event.guid in self._items:
                await self._progress(event)

    async def _progress(self, event: DownloadProgressEvent) -> None:
        guid = event.guid
        previous = self._items[guid]
        # Terminal CDP events can be repeated; never move an already completed file twice.
        if previous.state != DownloadState.IN_PROGRESS:
            return
        total = int(event.total_bytes) if event.total_bytes > 0 else None
        if event.state == DownloadState.IN_PROGRESS:
            await self._report_progress(previous, int(event.received_bytes), total)
            return
        path, error = event.file_path, None
        if event.state == DownloadState.COMPLETED and self._files is not None:
            try:
                path = await self._files.complete_download(
                    guid, previous.filename, path
                )
            except (OSError, ValueError) as failure:
                # A single missing file must not stop browser event processing.
                path, error = None, f"Downloaded file could not be saved: {failure}"
        download = Download(
            id=guid,
            url=previous.url,
            filename=previous.filename,
            state=DownloadState(event.state),
            received_bytes=int(event.received_bytes),
            total_bytes=total,
            path=path,
            error=error,
        )
        self._items[guid] = download
        self._progress_at.pop(guid, None)
        match download.state:
            case DownloadState.COMPLETED if error is not None:
                await self._emit(DownloadFailedEvent(download_id=guid, reason=error))
            case DownloadState.COMPLETED:
                await self._emit(
                    DownloadCompletedEvent(
                        download_id=guid,
                        filename=download.filename,
                        size=download.received_bytes,
                    )
                )
            case DownloadState.CANCELED:
                await self._emit(DownloadCanceledEvent(download_id=guid))

    async def _report_progress(
        self, download: Download, received: int, total: int | None
    ) -> None:
        self._items[download.id] = download.model_copy(
            update={"received_bytes": received, "total_bytes": total}
        )
        now = monotonic()
        if (
            now - self._progress_at.get(download.id, float("-inf"))
            < _PROGRESS_INTERVAL_SECONDS
        ):
            return
        self._progress_at[download.id] = now
        await self._emit(
            DownloadProgressedEvent(
                download_id=download.id, received_bytes=received, total_bytes=total
            )
        )
