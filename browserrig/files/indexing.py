from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from browserrig.core import Options

from .config import FileOptions
from .models import FileContent, FileExtraction
from .workspace import FileStat, Workspace, workspace_path

type _Reader = Callable[..., Awaitable[FileContent]]
type _Source = Callable[[str], Awaitable[Path]]


class Indexing:
    """Own bounded download indexing jobs and their durable per-selection cache."""

    def __init__(
        self,
        workspace: Workspace,
        options: FileOptions,
        *,
        read: _Reader,
        source: _Source,
    ):
        self._workspace = workspace
        self._options = options
        self._read = read
        self._source = source
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, FileExtraction] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def state(self, path: str) -> FileExtraction | None:
        return self._states.get(path)

    async def close(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks.values())

    async def start(self, path: str, *, url: str) -> None:
        if not self._options.auto_extract or (
            path in self._tasks and not self._tasks[path].done()
        ):
            return
        try:
            source = await self._stat(path)
            async with self._lock(path):
                manifest = await self._load(source)
                manifest.url, manifest.status = url, "processing"
                await self._publish(manifest)
            self._tasks[path] = asyncio.create_task(self._run(path))
        except (OSError, ValueError) as error:
            self._states[path] = FileExtraction(
                path=path + ".md",
                metadata_path=path + ".extraction.json",
                status="failed",
                error=str(error),
            )

    async def record(self, content: FileContent, *, source: FileStat) -> str | None:
        """Enrich an existing index after an explicit page/sheet read, including after reopening."""
        if content.member is not None or getattr(content, "image", None) is not None:
            return None
        path = content.path
        if (
            await self._workspace.stat(workspace_path(path + ".extraction.json"))
            is None
        ):
            return None
        async with self._lock(path):
            current = await self._stat(path)
            if (source.size, source.modified) != (current.size, current.modified):
                raise ValueError("Source changed before its Markdown could be updated")
            manifest = await self._load(current)
            await self._record(manifest, content)
            manifest.status = _status(manifest)
            manifest.error = None
            await self._publish(manifest)
        return path + ".md"

    async def _run(self, path: str) -> None:
        async with self._lock(path):
            manifest = None
            try:
                source = await self._stat(path)
                manifest = await self._load(source)
                await self._extract(manifest, source)
                manifest.status = _status(manifest)
                await self._publish(manifest)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Parsing cannot invalidate the original download.
                await self._failed(path, manifest, error)

    async def _extract(self, manifest: _Manifest, source: FileStat) -> None:
        if source.size is not None and source.size > self._options.max_file_bytes:
            raise ValueError("File exceeds max_file_bytes for automatic extraction")
        content = await self._read(manifest.source, ocr=False)
        manifest.incomplete = False
        manifest.error = None
        manifest.limitations = []
        manifest.sheets = list(content.sheets)
        if content.status == "unsupported":
            await self._record(manifest, content)
        elif content.format == "pdf":
            manifest.chunks.pop("document", None)
            await self._pdf(manifest)
        elif content.sheets:
            for sheet in content.sheets:
                selected = await self._read(manifest.source, sheet=sheet, ocr=False)
                await self._record(manifest, selected)
        elif content.page_number is not None and content.page_count is not None:
            await self._images(manifest, content)
        else:
            await self._record(manifest, content)

    async def _images(self, manifest: _Manifest, content: FileContent) -> None:
        count = content.page_count or 1
        manifest.page_count = count
        if count > self._options.max_index_pages:
            raise ValueError(
                "Image exceeds max_index_pages; read selected frames on demand"
            )
        manifest.pending_ocr_pages = [
            number
            for number in range(1, count + 1)
            if not (
                manifest.chunks.get(f"page:{number}")
                and manifest.chunks[f"page:{number}"].ocr
            )
        ]
        budget = self._options.auto_ocr_pages if self._options.ocr else 0
        if not budget:
            await self._record(manifest, content)
        for number in manifest.pending_ocr_pages[:budget]:
            selected = await self._read(manifest.source, page_number=number, ocr=True)
            await self._record(manifest, selected)

    async def _failed(
        self, path: str, manifest: _Manifest | None, error: Exception
    ) -> None:
        if manifest is not None:
            manifest.status, manifest.error = "failed", str(error)
            try:
                await self._publish(manifest, include_content=False)
                return
            except (OSError, ValueError):
                pass
        self._states[path] = FileExtraction(
            path=path + ".md",
            metadata_path=path + ".extraction.json",
            status="failed",
            error=str(error),
        )

    async def _pdf(self, manifest: _Manifest) -> None:
        local = await self._source(manifest.source)
        pages = await asyncio.to_thread(
            _pdf_text,
            local,
            self._options.max_expanded_bytes,
            self._options.max_index_pages,
        )
        manifest.page_count = len(pages)
        pending = set(manifest.pending_ocr_pages)
        for number, text in enumerate(pages, 1):
            key = f"page:{number}"
            if key not in manifest.chunks:
                await self._put(manifest, key, text, page=number)
                if not text.strip():
                    pending.add(number)
        manifest.pending_ocr_pages = sorted(pending)
        if self._options.ocr:
            for number in manifest.pending_ocr_pages[: self._options.auto_ocr_pages]:
                await self._record(
                    manifest,
                    await self._read(manifest.source, page_number=number, ocr=True),
                )
        manifest.limitations.append(
            "Native PDF text is indexed; graphics may require a visual read or explicit page OCR"
        )

    async def _record(self, manifest: _Manifest, content: FileContent) -> None:
        text = await self._text(content)
        has_text = bool(text.rsplit("\n\n> Extraction limitations:", 1)[0].strip())
        recognized = any(
            (
                "recognized with local OCR" in item
                or item.startswith("Local OCR extracts text")
            )
            for item in content.limitations
        )
        key = (
            f"page:{content.page_number}"
            if content.page_number
            else f"sheet:{content.sheet}:{content.cell_range}"
        )
        if content.page_number is None and content.sheet is None:
            key = "document"
        previous = manifest.chunks.get(key)
        if previous is None or recognized or not previous.ocr:
            await self._put(
                manifest,
                key,
                text,
                page=content.page_number,
                sheet=content.sheet,
                cell_range=content.cell_range,
                ocr=recognized,
            )
        manifest.page_count = content.page_count or manifest.page_count
        if (
            content.page_number
            and has_text
            and content.status not in {"metadata_only", "unsupported"}
            and content.page_number in manifest.pending_ocr_pages
        ):
            manifest.pending_ocr_pages.remove(content.page_number)
        manifest.limitations.extend(content.limitations)
        if content.status == "unsupported" or (
            content.status == "metadata_only" and content.page_count is None
        ):
            manifest.incomplete = True
        if any("initial view" in item for item in content.limitations):
            manifest.incomplete = True

    async def _text(self, content: FileContent) -> str:
        if content.extracted_path is not None:
            return await asyncio.to_thread(
                Path(content.extracted_path).read_text, encoding="utf-8"
            )
        if content.format == "text":
            source = await self._source(content.path)
            if source.stat().st_size > self._options.max_expanded_bytes:
                raise ValueError(
                    "Text exceeds max_expanded_bytes for automatic extraction"
                )
            return await asyncio.to_thread(
                source.read_text, encoding=content.encoding or "utf-8"
            )
        return content.text

    async def _put(
        self,
        manifest: _Manifest,
        key: str,
        text: str,
        *,
        page: int | None = None,
        sheet: str | None = None,
        cell_range: str | None = None,
        ocr: bool = False,
    ) -> None:
        digest = hashlib.sha256(key.encode()).hexdigest()[:24]
        path = f".content/index/{manifest.id}/{digest}.md"
        data = text.encode("utf-8")
        previous = manifest.chunks.get(key)
        total = sum(chunk.size for chunk in manifest.chunks.values()) - (
            previous.size if previous else 0
        )
        if total + len(data) > self._options.max_expanded_bytes:
            raise ValueError("Indexed text exceeds max_expanded_bytes")
        await self._workspace.write_bytes(workspace_path(path), data)
        manifest.chunks[key] = _Chunk(
            path=path,
            size=len(data),
            page=page,
            sheet=sheet,
            cell_range=cell_range,
            ocr=ocr,
        )

    async def _publish(
        self, manifest: _Manifest, *, include_content: bool = True
    ) -> None:
        manifest.limitations = list(dict.fromkeys(manifest.limitations))
        source = await self._stat(manifest.source)
        if (source.size, source.modified) != (manifest.size, manifest.modified):
            raise ValueError("Source changed during indexing; read it again")
        body = (
            f"# {PurePosixPath(manifest.source).name}\n\nSource file: {manifest.source}\n\n"
            f"Source URL: {manifest.url}\n\nExtraction status: {manifest.status}\n\n"
        )
        if manifest.page_count:
            body += (
                f"Pages: {manifest.page_count}; "
                f"OCR pending: {len(manifest.pending_ocr_pages)}.\n\n"
            )
        if manifest.pending_ocr_pages:
            body += (
                "Search covers extracted text only. "
                "Read pending pages with read_file to recognize their text.\n\n"
            )
        if manifest.error:
            body += f"> Extraction failed: {manifest.error}\n\n"
        parts = [body]
        size = len(body.encode())
        if include_content:
            chunks = sorted(
                manifest.chunks.values(),
                key=lambda chunk: (chunk.page or 0, chunk.sheet or "", chunk.path),
            )
            for chunk in chunks:
                if not chunk.path.startswith(f".content/index/{manifest.id}/"):
                    raise ValueError("Index chunk is outside its owned cache directory")
                heading = (
                    f"## Page {chunk.page}\n\n"
                    if chunk.page
                    else f"## {chunk.sheet or 'Document'}\n\n"
                )
                data = await self._workspace.read_bytes(workspace_path(chunk.path))
                size += len(heading.encode()) + len(data) + 2
                if size > self._options.max_expanded_bytes:
                    raise ValueError("Markdown sidecar exceeds max_expanded_bytes")
                parts.extend((heading, data.decode("utf-8"), "\n\n"))
        if manifest.limitations:
            parts.append(
                "> Extraction limitations:\n"
                + "".join(
                    f"> - {item}\n" for item in dict.fromkeys(manifest.limitations)
                )
            )
        metadata = workspace_path(manifest.source + ".extraction.json")
        markdown = workspace_path(manifest.source + ".md")
        await self._workspace.write_bytes(
            metadata, manifest.model_dump_json(indent=2).encode()
        )
        await self._workspace.write_bytes(markdown, "".join(parts).encode("utf-8"))
        self._states[manifest.source] = FileExtraction(
            path=str(markdown),
            metadata_path=str(metadata),
            status=manifest.status,
            page_count=manifest.page_count,
            indexed_pages=tuple(
                sorted(
                    chunk.page
                    for chunk in manifest.chunks.values()
                    if chunk.page and chunk.page not in manifest.pending_ocr_pages
                )
            ),
            pending_ocr_pages=tuple(manifest.pending_ocr_pages),
            error=manifest.error,
        )

    async def _load(self, source: FileStat) -> _Manifest:
        metadata = source.path.with_name(source.path.name + ".extraction.json")
        existing = await self._workspace.stat(metadata)
        if existing is not None:
            if (
                existing.size is not None
                and existing.size > self._options.max_expanded_bytes
            ):
                raise ValueError("Extraction metadata exceeds max_expanded_bytes")
            manifest = _Manifest.model_validate_json(
                await self._workspace.read_bytes(metadata)
            )
            if manifest.source != str(source.path):
                raise ValueError("Extraction metadata belongs to another source")
            if (source.size, source.modified) == (manifest.size, manifest.modified):
                return manifest
        elif await self._workspace.stat(
            source.path.with_name(source.path.name + ".md")
        ):
            raise FileExistsError(
                "Markdown sidecar exists and is not managed by Browserrig"
            )
        return _Manifest(
            source=str(source.path), size=source.size, modified=source.modified
        )

    async def _stat(self, path: str) -> FileStat:
        source = await self._workspace.stat(workspace_path(path))
        if source is None or source.is_directory:
            raise FileNotFoundError(path)
        return source

    def _lock(self, path: str) -> asyncio.Lock:
        return self._locks.setdefault(path, asyncio.Lock())


class _Chunk(Options):
    path: str
    size: int
    page: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    ocr: bool = False


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    source: str
    size: int | None
    modified: float
    url: str = ""
    status: Literal["processing", "complete", "partial", "failed"] = "processing"
    page_count: int | None = None
    sheets: list[str] = Field(default_factory=list)
    pending_ocr_pages: list[int] = Field(default_factory=list)
    chunks: dict[str, _Chunk] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    incomplete: bool = False
    error: str | None = None


def _status(manifest: _Manifest) -> Literal["complete", "partial"]:
    pages = {chunk.page for chunk in manifest.chunks.values() if chunk.page is not None}
    sheets = {
        chunk.sheet for chunk in manifest.chunks.values() if chunk.sheet is not None
    }
    missing_pages = (
        manifest.page_count is not None
        and "document" not in manifest.chunks
        and len(pages) < manifest.page_count
    )
    incomplete = manifest.pending_ocr_pages or manifest.incomplete or missing_pages
    return "partial" if incomplete or set(manifest.sheets) - sheets else "complete"


def _pdf_text(path: Path, max_bytes: int, max_pages: int) -> list[str]:
    pages, size = [], 0
    with path.open("rb") as stream:
        reader = import_module("pypdf").PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError(
                "PDF is encrypted; automatic extraction requires an unencrypted document"
            )
        if len(reader.pages) > max_pages:
            raise ValueError(
                f"PDF exceeds max_index_pages={max_pages}; read selected pages on demand"
            )
        for page in reader.pages:
            text = page.extract_text() or ""
            size += len(text.encode("utf-8"))
            if size > max_bytes:
                raise ValueError("PDF text exceeds max_expanded_bytes")
            pages.append(text)
    return pages
