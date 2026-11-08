import asyncio
import hashlib
import json
import tempfile
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from pathlib import Path
from types import TracebackType
from typing import Self

from .config import FileOptions
from .content import ReadRequest
from .models import FileContent, FileEntry, FileListing
from .reading import FileReader
from .workspace import FileStat, LocalWorkspace, Workspace, workspace_path


class FileSystem:
    """The agent's files: a workspace and the readers that parse it.

    Paths are relative to the workspace, such as `notes/summary.md`. The file system
    knows nothing about browsers; `FileTransfer` brings downloads in and hands files
    to Chrome. Construction creates nothing; entering the context enters a workspace
    that is an async context manager, and leaving it removes temporary copies.
    """

    def __init__(
        self, workspace: Workspace, options: FileOptions | None = None
    ) -> None:
        self.workspace = workspace
        self.options = options if options is not None else FileOptions()
        # Remote files are copied here to be parsed; local files are parsed in place.
        self._cache: tempfile.TemporaryDirectory[str] | None = None
        self._reader: FileReader | None = (
            FileReader(workspace.directory / ".content", self.options)
            if isinstance(workspace, LocalWorkspace)
            else None
        )
        self._exits = AsyncExitStack()

    async def __aenter__(self) -> Self:
        if isinstance(self.workspace, AbstractAsyncContextManager):
            await self._exits.enter_async_context(self.workspace)
        return self

    async def __aexit__(
        self,
        _type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Remove local copies of remote files; the workspace itself is kept."""
        try:
            if self._cache is not None:
                cache = self._cache
                self._cache = None
                self._reader = None
                await asyncio.to_thread(cache.cleanup)
        finally:
            await self._exits.aclose()

    async def exists(self, path: str) -> bool:
        return await self.workspace.stat(workspace_path(path)) is not None

    async def list_files(
        self, path: str = ".", *, offset: int = 0, limit: int = 100
    ) -> FileListing:
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("Use offset >= 0 and a limit between 1 and 200")
        directory = workspace_path(path)
        children = sorted(
            await self.workspace.list(directory),
            key=lambda child: child.path.name.casefold(),
        )
        return FileListing(
            directory=str(directory),
            entries=tuple(_entry(child) for child in children[offset : offset + limit]),
            next_offset=offset + limit if offset + limit < len(children) else None,
        )

    async def read_file(
        self,
        path: str,
        *,
        page_number: int | None = None,
        sheet: str | None = None,
        cell_range: str | None = None,
        member: str | None = None,
        ocr: bool | None = None,
        offset: int = 0,
        max_chars: int = 20000,
    ) -> FileContent:
        if offset < 0 or not 1 <= max_chars <= 200000:
            raise ValueError("Use offset >= 0 and max_chars between 1 and 200000")
        if page_number is not None and page_number < 1:
            raise ValueError("page_number must be at least 1")
        request = ReadRequest(
            page_number=page_number,
            sheet=sheet,
            cell_range=cell_range,
            member=member,
            ocr=ocr,
        )
        target = await self.file(path)
        if isinstance(self.workspace, LocalWorkspace):
            source = self.workspace.host_path(target.path)
        else:
            source = await self._local_copy(target)
        reader = self._reader
        assert reader is not None
        content = await asyncio.to_thread(
            reader.read, source, request, offset, max_chars
        )
        return content.model_copy(
            update={
                "path": str(target.path),
                "extracted_path": self._extracted_path(content.extracted_path),
            }
        )

    async def write_file(
        self, path: str, content: str, *, overwrite: bool = False
    ) -> FileEntry:
        target = workspace_path(path)
        data = content.encode("utf-8")
        if len(data) > self.options.max_file_bytes:
            raise ValueError("Content exceeds max_file_bytes")
        if not overwrite and await self.workspace.stat(target) is not None:
            raise FileExistsError(f"File exists: {target}; pass overwrite=true")
        await self.workspace.write_bytes(target, data)
        return FileEntry(
            path=str(target), name=target.name, is_directory=False, size=len(data)
        )

    async def file(self, path: str) -> FileStat:
        """An existing regular file in the workspace."""
        stat = await self.workspace.stat(workspace_path(path))
        if stat is None or stat.is_directory:
            raise FileNotFoundError(f"File not found: {path}")
        return stat

    async def _local_copy(self, stat: FileStat) -> Path:
        if stat.size is not None and stat.size > self.options.max_file_bytes:
            raise ValueError("File exceeds max_file_bytes for reading")
        if self._cache is None:
            # Lives as long as this file system; aclose removes it.
            self._cache = tempfile.TemporaryDirectory(  # pylint: disable=consider-using-with
                prefix="browserrig-"
            )
            self._reader = FileReader(Path(self._cache.name) / ".content", self.options)
        key = hashlib.sha256(
            json.dumps([str(stat.path), stat.size, stat.modified]).encode()
        ).hexdigest()[:32]
        # Keep the name: readers detect formats by suffix and report the file name.
        copy = Path(self._cache.name) / "sources" / key / stat.path.name
        if not copy.is_file():
            data = await self.workspace.read_bytes(stat.path)
            await asyncio.to_thread(_write_atomically, copy, data)
        return copy

    def _extracted_path(self, extracted: str | None) -> str | None:
        """Report a saved extraction only when the agent can read it in the workspace."""
        if extracted is None or not isinstance(self.workspace, LocalWorkspace):
            return None
        path = Path(extracted)
        if not path.is_relative_to(self.workspace.directory):
            return None
        return path.relative_to(self.workspace.directory).as_posix()


def _entry(stat: FileStat) -> FileEntry:
    return FileEntry(
        path=str(stat.path),
        name=stat.path.name,
        is_directory=stat.is_directory,
        size=stat.size,
    )


def _write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(data)
    temporary.replace(path)
