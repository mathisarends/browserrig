from pydantic import Field

from browserrig.core import Options


class FileOptions(Options):
    """Limits for the agent's file tools, and whether images and scans use OCR."""

    max_file_bytes: int = Field(default=50_000_000, ge=1)
    """Largest file the agent may parse or write."""
    max_expanded_bytes: int = Field(default=200_000_000, ge=1)
    max_archive_depth: int = Field(default=8, ge=1, le=32)
    ocr: bool = True
    auto_extract: bool = True
    """Create searchable Markdown beside completed browser downloads."""
    auto_ocr_pages: int = Field(default=3, ge=0, le=100)
    """Maximum scanned pages automatically recognized per downloaded document; 0 defers all OCR."""
    max_index_pages: int = Field(default=2000, ge=1)
    """Maximum document pages processed by an automatic indexing job."""
