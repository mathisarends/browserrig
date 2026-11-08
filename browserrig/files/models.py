from enum import StrEnum
from typing import Literal

from pydantic import Field

from browserrig.core import Options

type FileReadStatus = Literal["complete", "partial", "metadata_only", "unsupported"]


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
    total_bytes: int | None = None
    path: str | None = None
    """Workspace path once completed and saved; otherwise `None`."""
    error: str | None = None


class FileSystemState(Options):
    workspace: bool
    """Whether the agent has a workspace for file tools."""
    download_directory: str | None
    """Workspace directory for downloads; `None` while they stay on the browser host."""
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
    format: str = "text"
    status: FileReadStatus = "complete"
    size: int | None = None
    encoding: str | None = None
    extracted_path: str | None = None
    sheet: str | None = None
    sheets: tuple[str, ...] = ()
    cell_range: str | None = None
    member: str | None = None
    entry_count: int | None = None
