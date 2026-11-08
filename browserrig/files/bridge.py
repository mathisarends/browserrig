from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath, PureWindowsPath
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
    """Chrome sees the workspace directory at `browser_path`: no file is copied.

    Use it when Chrome runs on the agent's machine, or shares a volume with the
    workspace, as on one pod. Without `browser_path`, Chrome must see a
    `LocalWorkspace` at its own path. `browser_path` is absolute on the browser host.
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
        await workspace.create_directory(self._PENDING)
        return self._mounted(workspace, self._PENDING)

    async def receive(
        self,
        workspace: Workspace,
        download: BrowserDownload,
        destination: PurePosixPath,
    ) -> None:
        # Chrome names the file by its ID in the pending directory it was given.
        await workspace.move(self._PENDING / download.id, destination)

    async def send(
        self, workspace: Workspace, paths: Sequence[PurePosixPath]
    ) -> list[PurePath]:
        return [self._mounted(workspace, path) for path in paths]

    def _root(self, workspace: Workspace) -> PurePath:
        if self.browser_path is not None:
            return self.browser_path
        if isinstance(workspace, LocalWorkspace):
            return workspace.directory
        raise ValueError(
            "MountedWorkspace needs browser_path for a workspace that is not local"
        )

    def _mounted(self, workspace: Workspace, path: PurePosixPath) -> PurePath:
        return self._root(workspace).joinpath(*path.parts)


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
