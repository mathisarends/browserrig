from pathlib import Path

from pydantic import Field

from browserrig.browser.config import Options
from browserrig.browser.models import Download


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
