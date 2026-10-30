import re
from pathlib import Path
from uuid import uuid4

from .config import FileSystemOptions
from .content import ReadRequest
from .models import FileContent, FileEntry, FileListing
from .reading import FileReader


class FileSystem:
    """Local workspace and an optional separately configured download directory.

    Construction creates no files or directories. Browser startup initializes them;
    files persist after the browser closes. All paths are confined to these roots.
    """

    def __init__(
        self,
        options: FileSystemOptions | None = None,
        *,
        download_directory: str | None = None,
    ) -> None:
        self._options = options or FileSystemOptions()
        self.directory = (
            self._options.directory or Path(".browserrig/files") / uuid4().hex
        ).resolve()
        self.download_directory = (
            Path(download_directory).resolve()
            if download_directory is not None
            else self.directory / "downloads"
        )
        self.pending_directory = self.download_directory / ".pending"
        self._reader = FileReader(self.directory / ".content", self._options)

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pending_directory.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | Path) -> Path:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = self.directory / resolved
        resolved = resolved.resolve()
        if not any(
            resolved.is_relative_to(root) for root in (self.directory, self.download_directory)
        ):
            raise ValueError("Path is outside the agent workspace and download directory")
        return resolved

    def list_files(self, path: str = ".", *, offset: int = 0, limit: int = 100) -> FileListing:
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("Use offset >= 0 and a limit between 1 and 200")
        directory = self.resolve(path)
        children = sorted(directory.iterdir(), key=lambda child: child.name.casefold())
        entries = []
        for child in children[offset : offset + limit]:
            # Do not expose metadata for symlinks pointing outside the workspace.
            try:
                resolved = self.resolve(child)
            except ValueError:
                continue
            is_directory = resolved.is_dir()
            entries.append(
                FileEntry(
                    path=str(child),
                    name=child.name,
                    is_directory=is_directory,
                    size=None if is_directory else resolved.stat().st_size,
                )
            )
        return FileListing(
            directory=str(directory),
            entries=tuple(entries),
            next_offset=offset + limit if offset + limit < len(children) else None,
        )

    def read_file(
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
        resolved = self.resolve(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return self._reader.read(
            resolved,
            ReadRequest(
                page_number=page_number, sheet=sheet, cell_range=cell_range, member=member, ocr=ocr
            ),
            offset,
            max_chars,
        )

    def upload_paths(self, paths: list[str]) -> list[str]:
        """Validate the entire selection before passing host paths to Chrome."""
        if not paths:
            raise ValueError("Select at least one workspace file to upload")
        resolved = [self.resolve(path) for path in paths]
        for path in resolved:
            if not path.is_file():
                raise FileNotFoundError(f"Upload requires an existing file: {path}")
        return [str(path) for path in resolved]

    def write_file(self, path: str, content: str, *, overwrite: bool = False) -> FileEntry:
        resolved = self.resolve(path)
        data = content.encode("utf-8")
        if len(data) > self._options.max_file_bytes:
            raise ValueError("Content exceeds max_file_bytes")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("wb" if overwrite else "xb") as stream:
            stream.write(data)
        return FileEntry(path=str(resolved), name=resolved.name, is_directory=False, size=len(data))

    def complete_download(self, download_id: str, filename: str, path: str | None) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9-]+", download_id):
            raise ValueError("Invalid download ID")
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .") or "download"
        # Prefixing also handles Windows device names such as CON and NUL.
        if name.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)),
        }:
            name = "_" + name
        suffix = Path(name).suffix[:20]
        name = Path(name).stem[:160] + suffix
        source = self.resolve(path or self.pending_directory / download_id)
        destination = self.resolve(self.download_directory / download_id / name)
        if source != destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        if not destination.is_file():
            raise FileNotFoundError("Downloaded file is missing on disk; download it again")
        return str(destination)
