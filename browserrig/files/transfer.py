import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath, PurePosixPath

from .bridge import BrowserDownload, FileBridge
from .system import FileSystem

DOWNLOADS = PurePosixPath("downloads")

_WINDOWS_DEVICES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


@dataclass(frozen=True, slots=True)
class StagedFiles:
    """Workspace files made readable by Chrome."""

    paths: tuple[str, ...]
    """Workspace paths, in the order requested."""
    browser_paths: tuple[PurePath, ...]
    """The same files on the browser host."""


class FileTransfer:
    """Moves files between the agent's workspace and one browser through its bridge.

    Downloads land in the workspace at `downloads/<id>/<filename>`; workspace files
    are staged for Chrome to open or upload.
    """

    def __init__(self, files: FileSystem, bridge: FileBridge) -> None:
        self.files = files
        self.bridge = bridge

    async def download_directory(self) -> PurePath:
        """Where Chrome saves downloads on its host."""
        return await self.bridge.download_directory(self.files.workspace)

    async def receive(
        self, download_id: str, filename: str, url: str, browser_path: str | None
    ) -> str:
        """Bring a finished download into the workspace; return its workspace path."""
        if not re.fullmatch(r"[a-zA-Z0-9-]+", download_id):
            raise ValueError("Invalid download ID")
        destination = DOWNLOADS / download_id / _safe_name(filename)
        download = BrowserDownload(
            id=download_id, filename=filename, url=url, browser_path=browser_path
        )
        await self.bridge.receive(self.files.workspace, download, destination)
        saved = await self.files.workspace.stat(destination)
        if saved is None or saved.is_directory:
            raise FileNotFoundError(
                "Downloaded file is missing in the workspace; download it again"
            )
        return str(destination)

    async def stage(self, paths: Sequence[str]) -> StagedFiles:
        """Make workspace files readable by Chrome, validating the whole selection first."""
        if not paths:
            raise ValueError("Select at least one workspace file")
        targets = [(await self.files.file(path)).path for path in paths]
        browser_paths = await self.bridge.send(self.files.workspace, targets)
        if len(browser_paths) != len(targets):
            raise ValueError("The file bridge must return one browser path per file")
        return StagedFiles(
            paths=tuple(str(target) for target in targets),
            browser_paths=tuple(browser_paths),
        )


def _safe_name(filename: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .") or "download"
    # Prefixing also handles Windows device names such as CON and NUL.
    if name.split(".")[0].upper() in _WINDOWS_DEVICES:
        name = "_" + name
    suffix = PurePosixPath(name).suffix[:20]
    return PurePosixPath(name).stem[:160] + suffix
