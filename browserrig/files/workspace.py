import asyncio
import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import ClassVar, Protocol, runtime_checkable
from uuid import uuid4

_OUTSIDE = (
    "Path is outside the workspace; use a workspace-relative path such as "
    "downloads/<id>/report.pdf"
)


def workspace_path(path: str | PurePath) -> PurePosixPath:
    """Normalize a path from the model or calling code to a path inside the workspace.

    Both `/` and `\\` separate segments, and `.` is the workspace root. Absolute
    paths and paths that leave the workspace are rejected.
    """
    text = str(path).replace("\\", "/")
    if text.startswith("/") or PureWindowsPath(text).drive:
        raise ValueError(_OUTSIDE)
    normalized = posixpath.normpath(text or ".")
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(_OUTSIDE)
    return PurePosixPath(normalized)


@dataclass(frozen=True, slots=True)
class FileStat:
    path: PurePosixPath
    is_directory: bool
    size: int | None
    """`None` for directories."""
    modified: float
    """Seconds since the epoch."""


@runtime_checkable
class Workspace(Protocol):
    """Where the agent's files live: a local directory, a pod volume, a bucket.

    Implement it to keep agent files outside the agent's machine. Every path is
    relative to the workspace root and already normalized by `workspace_path`;
    `PurePosixPath(".")` is the root. Implementations must keep each path inside
    the workspace, including through links. Missing paths raise `FileNotFoundError`.

    A workspace that needs setup, such as opening a client, can also be an async
    context manager; the session enters it while the workspace is in use.
    """

    async def stat(self, path: PurePosixPath) -> FileStat | None:
        """Metadata for `path`, or `None` when nothing exists there."""
        ...

    async def list(self, path: PurePosixPath) -> Sequence[FileStat]:
        """Direct children of the directory at `path`, in any order."""
        ...

    async def read_bytes(self, path: PurePosixPath) -> bytes: ...

    async def write_bytes(
        self, path: PurePosixPath, data: bytes, *, overwrite: bool = True
    ) -> None:
        """Write a file, creating parents; atomically reject existing files if not overwrite.

        Raise `FileExistsError` when `overwrite=False` and the file already exists,
        including when another writer creates it concurrently.
        """
        ...


class LocalWorkspace:
    """A directory on the machine that runs the agent.

    Without `directory`, each instance uses a new directory under `default_root`.
    The directory is created with the first file; files outlive the session.
    """

    default_root: ClassVar[Path] = Path(".browserrig/files")

    def __init__(self, directory: str | Path | None = None) -> None:
        chosen = (
            Path(directory)
            if directory is not None
            else self.default_root / uuid4().hex
        )
        self.directory = chosen.resolve()

    def __repr__(self) -> str:
        return f"LocalWorkspace({str(self.directory)!r})"

    def host_path(self, path: PurePosixPath) -> Path:
        """The local path for `path`, rejecting links that resolve outside the workspace."""
        resolved = self.directory.joinpath(*path.parts).resolve()
        if not resolved.is_relative_to(self.directory):
            raise ValueError(_OUTSIDE)
        return resolved

    async def stat(self, path: PurePosixPath) -> FileStat | None:
        return await asyncio.to_thread(self._stat, path)

    async def list(self, path: PurePosixPath) -> Sequence[FileStat]:
        return await asyncio.to_thread(self._list, path)

    async def read_bytes(self, path: PurePosixPath) -> bytes:
        return await asyncio.to_thread(self.host_path(path).read_bytes)

    async def write_bytes(
        self, path: PurePosixPath, data: bytes, *, overwrite: bool = True
    ) -> None:
        await asyncio.to_thread(self._write, path, data, overwrite=overwrite)

    def _stat(self, path: PurePosixPath) -> FileStat | None:
        resolved = self.host_path(path)
        if not resolved.exists():
            return None
        stat = resolved.stat()
        directory = resolved.is_dir()
        return FileStat(
            path=path,
            is_directory=directory,
            size=None if directory else stat.st_size,
            modified=stat.st_mtime,
        )

    def _list(self, path: PurePosixPath) -> Sequence[FileStat]:
        if not path.parts and not self.directory.exists():
            return []  # Nothing has been written yet.
        entries = []
        for child in self.host_path(path).iterdir():
            # Links that leave the workspace are not listed, not even their metadata.
            try:
                stat = self._stat(path / child.name)
            except ValueError:
                continue
            if stat is not None:
                entries.append(stat)
        return entries

    def _write(self, path: PurePosixPath, data: bytes, *, overwrite: bool) -> None:
        resolved = self.host_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("wb" if overwrite else "xb") as stream:
            stream.write(data)
