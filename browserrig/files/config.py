from pathlib import Path

from pydantic import Field

from browserrig.browser.config import Options


class FileSystemOptions(Options):
    directory: Path | None = None
    max_file_bytes: int = Field(default=50_000_000, ge=1)
