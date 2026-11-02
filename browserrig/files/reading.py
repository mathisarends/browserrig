import hashlib
import json
import mimetypes
import re
import tarfile
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO
from zipfile import ZipFile, is_zipfile

from . import containers
from .config import FileSystemOptions
from .content import ParsedContent, ReadContext, ReadRequest
from .formats import READERS, signature_format
from .kinds import FileExtension as Ext
from .models import FileContent
from .text import read_text, text_encoding, text_result

_UNSUPPORTED = {
    Ext.DOC,
    Ext.PPT,
    Ext.XLSB,
    Ext.MSG,
    Ext.SEVEN_ZIP,
    Ext.RAR,
    Ext.PARQUET,
    Ext.ARROW,
    Ext.FEATHER,
    Ext.AVRO,
    Ext.HDF5,
    Ext.H5,
    Ext.NETCDF,
    Ext.NC,
    Ext.MOBI,
    Ext.AZW,
    Ext.PAGES,
    Ext.NUMBERS,
    Ext.KEY,
    Ext.EXE,
    Ext.DLL,
}
_CACHE_VERSION = 4


class FileReader:
    def __init__(self, cache_directory: Path, options: FileSystemOptions) -> None:
        self.directory = cache_directory
        self.options = options

    def read(
        self,
        path: Path,
        request: ReadRequest,
        offset: int,
        max_chars: int,
        *,
        depth: int = 0,
    ) -> FileContent:
        try:
            return self._read(path, request, offset, max_chars, depth)
        except (OSError, ValueError):
            raise
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Could not read {path.name}: {error}") from error

    def _read(
        self, path: Path, request: ReadRequest, offset: int, max_chars: int, depth: int
    ) -> FileContent:
        with path.open("rb") as stream:
            sample = stream.read(65536)
        format_ = _format(path, sample)
        if format_ in READERS and path.stat().st_size > self.options.max_file_bytes:
            raise ValueError("File exceeds max_file_bytes for document parsing")
        if request.member is not None:
            return self._read_member(
                path, format_, request, offset=offset, max_chars=max_chars, depth=depth
            )
        _validate_selection(format_, request)
        if format_ == "text":
            encoding = text_encoding(sample)
            if encoding is not None:
                result = text_result(path, encoding, offset, max_chars)
                return result.model_copy(
                    update={
                        "media_type": mimetypes.guess_type(path.name)[0]
                        or "text/plain",
                    }
                )
            return _unsupported(
                path,
                format_,
                "The file contains binary data or an unrecognized text encoding",
                offset,
                max_chars,
            )
        if format_ in _UNSUPPORTED or format_ == "binary":
            return _unsupported(
                path,
                format_,
                "No local content reader is available for this format",
                offset,
                max_chars,
            )
        key = self._key(path, request)
        content_path = self._cache_path(f"{key}.md")
        metadata_path = self._cache_path(f"{key}.json")
        if not content_path.is_file() or not metadata_path.is_file():
            self._extract(path, format_, request, content_path, metadata_path)
        details = FileContent.model_validate_json(
            metadata_path.read_text(encoding="utf-8")
        )
        text = read_text(content_path, "utf-8", offset, max_chars)
        return details.model_copy(
            update={
                "text": text[:max_chars],
                "offset": offset,
                "next_offset": offset + max_chars if len(text) > max_chars else None,
                "extracted_path": str(content_path),
            }
        )

    def _cache_path(self, name: str) -> Path:
        root = self.directory.parent.resolve()
        directory = self.directory.resolve()
        if not directory.is_relative_to(root):
            raise ValueError("Content cache is outside the workspace")
        path = directory / name
        if not path.resolve().is_relative_to(directory):
            raise ValueError("Content cache file is outside the cache directory")
        return path

    def _key(self, path: Path, request: ReadRequest) -> str:
        stat = path.stat()
        source = (
            str(path),
            stat.st_mtime_ns,
            stat.st_size,
            asdict(request),
            self.options.model_dump(),
            _CACHE_VERSION,
        )
        return hashlib.sha256(
            json.dumps(source, default=str, sort_keys=True).encode()
        ).hexdigest()

    def _extract(
        self,
        path: Path,
        format_: str,
        request: ReadRequest,
        target: Path,
        metadata: Path,
    ) -> None:
        directory = self._cache_path(".")
        directory.mkdir(parents=True, exist_ok=True)
        before = path.stat()
        temporary = None
        try:
            if not READERS[format_].members and is_zipfile(path):
                with ZipFile(path) as archive:
                    if (
                        sum(item.file_size for item in archive.infolist())
                        > self.options.max_expanded_bytes
                    ):
                        raise ValueError("Expanded document exceeds max_expanded_bytes")
            details = self._parse(path, format_, request)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=directory, delete=False
            ) as stream:
                temporary = Path(stream.name)
                for block in details.blocks:
                    _write_block(stream.file, block, self.options.max_expanded_bytes)
                if details.limitations:
                    _write_block(
                        stream.file,
                        "\n\n> Extraction limitations:\n",
                        self.options.max_expanded_bytes,
                    )
                    for item in dict.fromkeys(details.limitations):
                        _write_block(
                            stream.file,
                            f"> - {item}\n",
                            self.options.max_expanded_bytes,
                        )
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError(
                    "File changed during extraction; read the current file again"
                )
            result = details.result(
                path=str(path),
                text="",
                size=after.st_size,
                media_type=mimetypes.guess_type("file." + format_)[0]
                or "application/octet-stream",
            )
            temporary.replace(target)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(result.model_dump_json())
            temporary.replace(metadata)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _parse(self, path: Path, format_: str, request: ReadRequest) -> ParsedContent:
        spec = READERS.get(format_)
        if spec is None:
            raise ValueError(f"No content reader for {format_}")
        return spec.read(ReadContext(path, format_, request, self.options))

    def _read_member(
        self,
        path: Path,
        format_: str,
        request: ReadRequest,
        *,
        offset: int,
        max_chars: int,
        depth: int,
    ) -> FileContent:
        if depth >= self.options.max_archive_depth:
            raise ValueError("Nested container selection exceeds max_archive_depth")
        spec = READERS.get(format_)
        if spec is None or not spec.members:
            raise ValueError(
                "member is only supported for containers and email attachments"
            )
        assert request.member is not None
        member, separator, nested = request.member.partition("!/")
        extracted = self._entry_source(path, format_, member)
        result = self.read(
            extracted,
            replace(request, member=nested if separator else None),
            offset,
            max_chars,
            depth=depth + 1,
        )
        return result.model_copy(update={"path": str(path), "member": request.member})

    def _entry_source(self, path: Path, format_: str, member: str) -> Path:
        directory = self._cache_path(".")
        directory.mkdir(parents=True, exist_ok=True)
        key = self._key(path, ReadRequest(member=member))
        metadata = self._cache_path(f"{key}.entry.json")
        if metadata.is_file():
            name = json.loads(metadata.read_text(encoding="utf-8"))["name"]
            cached = self._entry_path(key, name)
            if cached.is_file():
                return cached
        temporary = None
        try:
            with NamedTemporaryFile(dir=directory, delete=False) as stream:
                temporary = Path(stream.name)
                name = containers.copy_entry(
                    path, format_, member, stream, self.options.max_expanded_bytes
                )
            if key != self._key(path, ReadRequest(member=member)):
                raise ValueError(
                    "Container changed during extraction; read the current file again"
                )
            extracted = self._entry_path(key, name)
            temporary.replace(extracted)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"name": name}, stream)
            temporary.replace(metadata)
            return extracted
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _entry_path(self, key: str, name: str) -> Path:
        suffix = Path(name).suffix
        if not re.fullmatch(r"\.[a-zA-Z0-9]{1,12}", suffix):
            suffix = ""
        return self._cache_path(f"{key}.source{suffix}")


def _write_block(stream: IO[str], block: str, limit: int) -> None:
    if stream.tell() + len(block.encode("utf-8")) > limit:
        raise ValueError("Extracted content exceeds max_expanded_bytes")
    stream.write(block)


def _format(path: Path, sample: bytes) -> str:
    # pylint: disable=too-many-return-statements,too-many-branches
    suffix = path.suffix.lower().lstrip(".")
    detected = signature_format(sample)
    if detected is not None:
        return detected
    if is_zipfile(path):
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" in names:
                return (
                    suffix
                    if suffix in {Ext.XLSX, Ext.XLSM, Ext.XLTX, Ext.XLTM}
                    else Ext.XLSX
                )
            if "word/document.xml" in names:
                return Ext.DOCX
            if "ppt/presentation.xml" in names:
                return Ext.PPTX
            if "META-INF/container.xml" in names:
                return Ext.EPUB
            if "mimetype" in names:
                with archive.open("mimetype") as stream:
                    mime = stream.read(256)
                for name, type_ in (
                    (b"spreadsheet", Ext.ODS),
                    (b"presentation", Ext.ODP),
                    (b"text", Ext.ODT),
                ):
                    if b"opendocument" in mime and name in mime:
                        return type_
            return Ext.ZIP
    if sample.startswith(b"\xd0\xcf\x11\xe0"):
        return (
            Ext.XLS
            if suffix == Ext.XLS
            else suffix
            if suffix in _UNSUPPORTED
            else "binary"
        )
    if suffix in {Ext.TAR, Ext.TGZ, Ext.TBZ2, Ext.TXZ, Ext.GZ, Ext.BZ2, Ext.XZ}:
        if tarfile.is_tarfile(path):
            return Ext.TAR
        return suffix
    if suffix in READERS or suffix in _UNSUPPORTED:
        return suffix
    if suffix in {
        Ext.HTML,
        Ext.HTM,
        Ext.XHTML,
        Ext.SVG,
    } or sample.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return Ext.HTML
    if suffix in {Ext.MHT, Ext.MHTML}:
        return Ext.MHTML
    return "text" if text_encoding(sample) is not None else "binary"


def _validate_selection(format_: str, request: ReadRequest) -> None:
    spec = READERS.get(format_)
    if request.page_number is not None and (spec is None or not spec.pages):
        raise ValueError(
            "page_number is only supported for PDF pages, presentation slides and image frames"
        )
    if request.sheet is not None and (spec is None or not spec.sheets):
        raise ValueError(
            "sheet is only supported for spreadsheets, delimited tables and SQLite databases"
        )
    if request.cell_range is not None and (spec is None or not spec.cell_ranges):
        raise ValueError(
            "cell_range is only supported for spreadsheets and delimited tables"
        )


def _unsupported(
    path: Path, format_: str, reason: str, offset: int, max_chars: int
) -> FileContent:
    text = f"Name: {path.name}\nSize: {path.stat().st_size} bytes\nFormat: {format_}"
    return FileContent(
        path=str(path),
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        text=text[offset : offset + max_chars],
        offset=offset,
        next_offset=offset + max_chars if len(text) > offset + max_chars else None,
        size=path.stat().st_size,
        format=format_,
        status="unsupported",
        limitations=(reason,),
    )
