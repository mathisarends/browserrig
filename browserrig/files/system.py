import asyncio
import hashlib
import json
import tempfile
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Literal, Self

from harnessed.tracing import traced

from .config import FileOptions
from .content import ReadRequest
from .indexing import Indexing
from .models import FileContent, FileEntry, FileExtraction, FileListing
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
        self._indexing = Indexing(
            workspace, self.options, read=self._index_read, source=self._index_source
        )
        # Remote files are copied here to be parsed; local files are parsed in place.
        self._cache: tempfile.TemporaryDirectory[str] | None = None
        self._reader: FileReader | None = (
            FileReader(workspace.directory / ".content", self.options)
            if isinstance(workspace, LocalWorkspace)
            else None
        )
        self._exits = AsyncExitStack()
        self._copy_locks: dict[str, asyncio.Lock] = {}
        self._edit_locks: dict[str, asyncio.Lock] = {}

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
            await self._indexing.close()
            if self._cache is not None:
                cache = self._cache
                self._cache = None
                self._reader = None
                await asyncio.to_thread(cache.cleanup)
        finally:
            await self._exits.aclose()

    async def exists(self, path: str) -> bool:
        return await self.workspace.stat(workspace_path(path)) is not None

    @traced
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

    async def start_extraction(self, path: str, *, url: str = "") -> None:
        """Create a Markdown sidecar and start bounded background document indexing."""
        await self._indexing.start(str(workspace_path(path)), url=url)

    def extraction(self, path: str) -> FileExtraction | None:
        return self._indexing.state(str(workspace_path(path)))

    @traced
    async def read_file(
        self,
        path: str,
        *,
        page_number: int | None = None,
        sheet: str | None = None,
        cell_range: str | None = None,
        member: str | None = None,
        ocr: bool | None = None,
        view: Literal["auto", "text", "image"] = "text",
        offset: int = 0,
        max_chars: int = 20000,
    ) -> FileContent:
        if offset < 0 or not 1 <= max_chars <= 200000:
            raise ValueError("Use offset >= 0 and max_chars between 1 and 200000")
        if page_number is not None and page_number < 1:
            raise ValueError("page_number must be at least 1")
        if view not in {"auto", "text", "image"}:
            raise ValueError("view must be auto, text or image")
        request = ReadRequest(
            page_number=page_number,
            sheet=sheet,
            cell_range=cell_range,
            member=member,
            ocr=ocr,
            view=view,
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
        document_path = None
        try:
            document_path = await self._indexing.record(
                content.model_copy(update={"path": str(target.path)}), source=target
            )
        except (OSError, ValueError) as error:
            content = content.model_copy(
                update={
                    "status": "partial"
                    if content.status == "complete"
                    else content.status,
                    "limitations": (
                        *content.limitations,
                        f"Markdown sidecar could not be updated: {error}",
                    ),
                }
            )
        content = content.model_copy(update={"document_path": document_path})
        return content.model_copy(
            update={
                "path": str(target.path),
                "extracted_path": self._extracted_path(content.extracted_path),
                **_continuation(content),
            }
        )

    @traced
    async def write_file(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        append: bool = False,
    ) -> FileEntry:
        """Save UTF-8 text; `append` adds to the end and creates a missing file."""
        if overwrite and append:
            raise ValueError("Pass either overwrite=true or append=true, not both")
        target = workspace_path(path)
        data = content.encode("utf-8")
        if append:
            async with self._edit_lock(target):
                existing = await self.workspace.stat(target)
                if existing is not None:
                    if existing.is_directory:
                        raise IsADirectoryError(f"Not a file: {target}")
                    data = await self.workspace.read_bytes(target) + data
                return await self._save(target, data, overwrite=existing is not None)
        try:
            return await self._save(target, data, overwrite=overwrite)
        except FileExistsError as error:
            raise FileExistsError(
                f"File exists: {target}; pass overwrite=true or append=true"
            ) from error

    @traced
    async def edit_file(
        self, path: str, old_text: str, new_text: str, *, replace_all: bool = False
    ) -> FileEntry:
        """Replace `old_text` in a UTF-8 file; it must match exactly once unless `replace_all`."""
        if not old_text:
            raise ValueError("old_text must not be empty")
        if old_text == new_text:
            raise ValueError("old_text and new_text are identical")
        target = workspace_path(path)
        async with self._edit_lock(target):
            stat = await self.file(path)
            try:
                text = (await self.workspace.read_bytes(stat.path)).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(
                    f"{target} is not UTF-8 text; edit_file only changes text files"
                ) from error
            matches = text.count(old_text)
            if matches == 0:
                raise ValueError(f"old_text not found in {target}")
            if matches > 1 and not replace_all:
                raise ValueError(
                    f"old_text matches {matches} places in {target}; include more "
                    "surrounding text or pass replace_all=true"
                )
            updated = text.replace(old_text, new_text)
            return await self._save(target, updated.encode("utf-8"), overwrite=True)

    async def _save(
        self, target: PurePosixPath, data: bytes, *, overwrite: bool
    ) -> FileEntry:
        if len(data) > self.options.max_file_bytes:
            raise ValueError("Content exceeds max_file_bytes")
        await self.workspace.write_bytes(target, data, overwrite=overwrite)
        return FileEntry(
            path=str(target), name=target.name, is_directory=False, size=len(data)
        )

    def _edit_lock(self, target: PurePosixPath) -> asyncio.Lock:
        # Serializes read-modify-write changes to one file within this file system.
        return self._edit_locks.setdefault(str(target), asyncio.Lock())

    async def file(self, path: str) -> FileStat:
        """An existing regular file in the workspace."""
        stat = await self.workspace.stat(workspace_path(path))
        if stat is None or stat.is_directory:
            raise FileNotFoundError(f"File not found: {path}")
        return stat

    @traced
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
        async with self._copy_locks.setdefault(key, asyncio.Lock()):
            if not copy.is_file():
                data = await self.workspace.read_bytes(stat.path)
                await asyncio.to_thread(_write_atomically, copy, data)
        return copy

    async def _index_source(self, path: str) -> Path:
        target = await self.file(path)
        if isinstance(self.workspace, LocalWorkspace):
            return self.workspace.host_path(target.path)
        return await self._local_copy(target)

    async def _index_read(self, path: str, **selectors) -> FileContent:
        source = await self._index_source(path)
        reader = self._reader
        assert reader is not None
        content = await asyncio.to_thread(
            reader.read, source, ReadRequest(**selectors), 0, 200000
        )
        return content.model_copy(update={"path": path})

    def _extracted_path(self, extracted: str | None) -> str | None:
        """Report a saved extraction only when the agent can read it in the workspace."""
        if extracted is None or not isinstance(self.workspace, LocalWorkspace):
            return None
        path = Path(extracted)
        if not path.is_relative_to(self.workspace.directory):
            return None
        return path.relative_to(self.workspace.directory).as_posix()


def _continuation(content: FileContent) -> dict[str, int | str | None]:
    page, sheet = None, None
    if content.next_offset is None:
        if (
            content.page_number is not None
            and content.page_count is not None
            and content.page_number < content.page_count
        ):
            page = content.page_number + 1
        if content.sheet is not None and content.sheet in content.sheets:
            index = content.sheets.index(content.sheet)
            if index + 1 < len(content.sheets):
                sheet = content.sheets[index + 1]
    return {"next_page_number": page, "next_sheet": sheet}


def _entry(stat: FileStat) -> FileEntry:
    return FileEntry(
        path=str(stat.path),
        name=stat.path.name,
        is_directory=stat.is_directory,
        size=stat.size,
    )


def _write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
