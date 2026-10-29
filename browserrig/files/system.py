import mimetypes
import re
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .config import FileSystemOptions
from .models import FileContent, FileEntry, FileListing


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
        offset: int = 0,
        max_chars: int = 20000,
    ) -> FileContent:
        if offset < 0 or not 1 <= max_chars <= 200000:
            raise ValueError("Use offset >= 0 and max_chars between 1 and 200000")
        resolved = self.resolve(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        if resolved.stat().st_size > self._options.max_file_bytes:
            raise ValueError("File exceeds max_file_bytes; use open_file to view it in the browser")
        if resolved.suffix.lower() == ".pdf":
            return self._read_pdf(
                resolved, 1 if page_number is None else page_number, offset, max_chars
            )
        if page_number is not None:
            raise ValueError("page_number is only supported for PDF files")
        try:
            with resolved.open(encoding="utf-8-sig", newline="") as stream:
                # Read characters rather than seeking into a possibly multibyte encoding.
                remaining = offset
                while remaining:
                    chunk = stream.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                text = stream.read(max_chars + 1)
        except UnicodeError as error:
            raise ValueError(
                "File is not UTF-8 text; use open_file for visual inspection"
            ) from error
        if "\x00" in text:
            raise ValueError("File is binary; use open_file for visual inspection")
        return FileContent(
            path=str(resolved),
            media_type=mimetypes.guess_type(resolved.name)[0] or "text/plain",
            text=text[:max_chars],
            offset=offset,
            next_offset=offset + max_chars if len(text) > max_chars else None,
        )

    def _read_pdf(self, path: Path, page_number: int, offset: int, max_chars: int) -> FileContent:
        try:
            with path.open("rb") as stream:
                reader = PdfReader(stream)
                if reader.is_encrypted:
                    raise ValueError("PDF is encrypted; use open_file to inspect it in the browser")
                page_count = len(reader.pages)
                if not 1 <= page_number <= page_count:
                    raise ValueError(f"PDF has {page_count} pages; choose an existing page_number")
                text = reader.pages[page_number - 1].extract_text() or ""
        except PyPdfError as error:
            raise ValueError(f"Could not read PDF: {error}") from error
        return FileContent(
            path=str(path),
            media_type="application/pdf",
            text=text[offset : offset + max_chars],
            offset=offset,
            next_offset=offset + max_chars if len(text) > offset + max_chars else None,
            page_number=page_number,
            page_count=page_count,
            limitations=()
            if text.strip()
            else ("No extractable text on this page. Use open_file and screenshot to inspect it.",),
        )

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
