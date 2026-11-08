from pydantic import Field

from browserrig.core import Options


class FileOptions(Options):
    """Limits for the agent's file tools, and whether images and scans use OCR."""

    max_file_bytes: int = Field(default=50_000_000, ge=1)
    """Largest file the agent may parse or write."""
    max_expanded_bytes: int = Field(default=200_000_000, ge=1)
    max_archive_depth: int = Field(default=8, ge=1, le=32)
    ocr: bool = True
