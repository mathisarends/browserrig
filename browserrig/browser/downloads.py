import asyncio

from cdpify import CdpClient
from cdpify.domains.browser import DownloadProgressEvent, DownloadWillBeginEvent

from browserrig.events import DownloadCompletedEvent, DownloadFailedEvent, DownloadStartedEvent
from browserrig.files import FileSystem
from browserrig.files.models import Download, DownloadState

from .base import EventSink


class Downloads:
    """Track browser downloads and move completed files into the workspace."""

    def __init__(self, files: FileSystem | None, directory: str | None, emit: EventSink) -> None:
        self._files = files
        self._directory = directory
        self._emit = emit
        self._items: dict[str, Download] = {}

    async def enable(self, client: CdpClient, context_id: str | None) -> None:
        directory = str(self._files.pending_directory) if self._files else self._directory
        if directory is not None:
            await client.browser.set_download_behavior(
                behavior="allowAndName",
                download_path=directory,
                browser_context_id=context_id,
                events_enabled=True,
            )

    def all(self) -> tuple[Download, ...]:
        return tuple(self._items.values())

    async def handle(self, event: DownloadWillBeginEvent | DownloadProgressEvent) -> None:
        match event:
            case DownloadWillBeginEvent():
                self._items[event.guid] = Download(
                    id=event.guid, url=event.url, filename=event.suggested_filename
                )
                await self._emit(
                    DownloadStartedEvent(
                        download_id=event.guid, filename=event.suggested_filename, url=event.url
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
        path, error = event.file_path, None
        if event.state == DownloadState.COMPLETED and self._files is not None:
            try:
                path = await asyncio.to_thread(
                    self._files.complete_download, guid, previous.filename, path
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
            path=path,
            error=error,
        )
        self._items[guid] = download
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
                await self._emit(
                    DownloadFailedEvent(download_id=guid, reason="Download canceled by browser")
                )
