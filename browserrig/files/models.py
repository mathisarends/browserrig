from enum import StrEnum
from pathlib import Path

from pydantic import Field

from browserrig.core.options import Options


class DownloadState(StrEnum):
    IN_PROGRESS = "inProgress"
    COMPLETED = "completed"
    CANCELED = "canceled"


class Download(Options):
    id: str
    filename: str
    url: str
    state: DownloadState = DownloadState.IN_PROGRESS
    received_bytes: int = 0
    path: str | None = None
    error: str | None = None


class FileSystemState(Options):
    directory: Path | None
    download_directory: Path | None
    downloads: tuple[Download, ...]
    total_downloads: int = Field(ge=0)


class FileSystemView(Options):
    file_system: FileSystemState


class FileEntry(Options):
    path: str
    name: str
    is_directory: bool
    size: int | None = None


class FileListing(Options):
    directory: str
    entries: tuple[FileEntry, ...]
    next_offset: int | None = None


class FileContent(Options):
    path: str
    media_type: str
    text: str
    offset: int = 0
    next_offset: int | None = None
    page_number: int | None = None
    page_count: int | None = None
    limitations: tuple[str, ...] = ()
