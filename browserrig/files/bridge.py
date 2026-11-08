import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Protocol, runtime_checkable

from .workspace import LocalWorkspace, Workspace


@dataclass(frozen=True, slots=True)
class BrowserDownload:
    """A download Chrome finished saving on the machine it runs on."""

    id: str
    """Chrome's download GUID; also the file name in the download directory."""
    filename: str
    """The name the site suggested, unsanitized."""
    url: str
    browser_path: str | None
    """Where Chrome reports the file, on the browser host; may be missing."""


@runtime_checkable
class FileBridge(Protocol):
    """Moves files between the agent's workspace and the machine that runs Chrome.

    Chrome saves downloads to, and reads uploads from, its own file system. A bridge
    connects that file system to the workspace: `MountedWorkspace` when both share a
    disk, or a cloud browser provider's file API for a browser running elsewhere.
    """

    async def download_directory(self, workspace: Workspace) -> PurePath:
        """Directory on the browser host where Chrome saves downloads.

        Chrome names each file there by its download ID. Runs once per browser.
        """
        ...

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        """Store a finished download in the workspace at `destination`."""
        ...

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        """Make existing workspace files readable by Chrome.

        Return each file's path on the browser host, in order; Chrome uploads
        from and opens these paths.
        """
        ...


class MountedWorkspace:
    """Chrome sees a `LocalWorkspace`'s directory at `browser_path`: no file is copied.

    Use it when Chrome runs on the agent's machine, or shares a volume with the
    workspace, as on one pod. Without `browser_path`, Chrome sees the directory at
    the agent's path. `browser_path` is absolute on the browser host. A workspace
    the agent reaches only through an API needs its own `FileBridge`.
    """

    _PENDING = PurePosixPath("downloads/.pending")

    def __init__(self, browser_path: str | PurePath | None = None) -> None:
        self.browser_path = None if browser_path is None else _host_path(browser_path)

    def __repr__(self) -> str:
        path = None if self.browser_path is None else str(self.browser_path)
        return f"MountedWorkspace({path!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MountedWorkspace):
            return NotImplemented
        return self.browser_path == other.browser_path

    def __hash__(self) -> int:
        return hash(self.browser_path)

    async def download_directory(self, workspace: Workspace) -> PurePath:
        pending = _local(workspace).host_path(self._PENDING)
        await asyncio.to_thread(pending.mkdir, parents=True, exist_ok=True)
        return self._mounted(workspace, self._PENDING)

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        local = _local(workspace)
        # Chrome names the file by its ID in the pending directory it was given.
        source = local.host_path(self._PENDING / download.id)
        await asyncio.to_thread(_move, source, local.host_path(destination))

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        return [self._mounted(workspace, path) for path in paths]

    def _mounted(self, workspace: Workspace, path: PurePosixPath) -> PurePath:
        root = self.browser_path or _local(workspace).directory
        return root.joinpath(*path.parts)


def _local(workspace: Workspace) -> LocalWorkspace:
    if not isinstance(workspace, LocalWorkspace):
        raise ValueError(
            "MountedWorkspace needs a LocalWorkspace; "
            "implement a FileBridge for a remote workspace"
        )
    return workspace


def _move(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"File exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)


def _host_path(path: str | PurePath) -> PurePath:
    """Keep the browser host's path style even when the agent runs on another OS."""
    if isinstance(path, PurePath):
        parsed = path
    elif PureWindowsPath(path).drive or "\\" in path:
        parsed = PureWindowsPath(path)
    else:
        parsed = PurePosixPath(path)
    if not parsed.is_absolute():
        raise ValueError("browser_path must be absolute on the browser host")
    return parsed
