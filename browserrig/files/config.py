from pathlib import Path

from pydantic import Field

from browserrig.core import Options


class FileSystemOptions(Options):
    directory: Path | None = None
    max_file_bytes: int = Field(default=50_000_000, ge=1)
    max_expanded_bytes: int = Field(default=200_000_000, ge=1)
    max_archive_depth: int = Field(default=8, ge=1, le=32)
    ocr: bool = True
