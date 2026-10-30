import bz2
import gzip
import lzma
import mailbox
import stat
import tarfile
from collections.abc import Iterator
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Protocol
from zipfile import ZipFile

from .content import ParsedContent, cell_text


def container_index(path: Path, format_: str, limit: int) -> ParsedContent:
    details = ParsedContent((), format_)

    def blocks() -> Iterator[str]:
        yield "# Container entries\n\nRead an entry by passing member=its name.\n\n"
        if format_ == "zip":
            with ZipFile(path) as archive:
                details.entry_count = len(archive.infolist())
                for entry in archive.infolist():
                    yield (
                        f"- {cell_text(entry.filename)} ({entry.file_size} bytes)"
                        + (" [encrypted]" if entry.flag_bits & 1 else "")
                        + "\n"
                    )
        elif format_ == "tar":
            with tarfile.open(path) as archive:
                count = 0
                for entry in _tar_entries(archive, limit):
                    count += 1
                    kind = (
                        "file"
                        if entry.isfile()
                        else "directory"
                        if entry.isdir()
                        else "link or special entry"
                    )
                    yield f"- {cell_text(entry.name)} ({entry.size} bytes; {kind})\n"
                details.entry_count = count
        elif format_ == "mbox":
            archive = mailbox.mbox(path, create=False)
            try:
                details.entry_count = len(archive)
                for index, message in enumerate(archive, 1):
                    subject = " ".join(str(message.get("Subject", "Untitled")).split())
                    yield f"- #{index}: {subject}\n"
            finally:
                archive.close()
        elif format_ == "eml":
            with path.open("rb") as stream:
                message = BytesParser(policy=policy.default).parse(stream)
            entries = list(message.iter_attachments())
            details.entry_count = len(entries)
            for index, part in enumerate(entries, 1):
                name = part.get_filename() or f"attachment-{index}"
                yield f"- #{index}: {cell_text(name)} ({part.get_content_type()})\n"
        else:
            details.entry_count = 1
            yield f"- {cell_text(path.stem)}\n"

    details.blocks = blocks()
    return details


def copy_entry(path: Path, format_: str, name: str, target: IO[bytes], limit: int) -> str:
    _safe_member(name)
    if format_ == "zip":
        with ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename == name]
            if len(entries) != 1:
                raise ValueError("Container entry was not found or its name is ambiguous")
            entry = entries[0]
            if entry.is_dir() or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ValueError("Only regular container files can be read")
            if entry.flag_bits & 1:
                raise ValueError("Container entry is encrypted; a password is required")
            if entry.file_size > limit:
                raise ValueError("Container entry exceeds max_expanded_bytes")
            with archive.open(entry) as source:
                _copy(source, target, limit)
    elif format_ == "tar":
        with tarfile.open(path) as archive:
            entries = [entry for entry in _tar_entries(archive, limit) if entry.name == name]
            if len(entries) != 1 or not entries[0].isfile():
                raise ValueError(
                    "Container entry was not found, is ambiguous, or is not a regular file"
                )
            source = archive.extractfile(entries[0])
            if source is None:
                raise ValueError("Container entry cannot be read")
            with source:
                _copy(source, target, limit)
    elif format_ in {"eml", "mbox"}:
        return _copy_message(path, format_, name, target, limit)
    elif format_ in {"gz", "bz2", "xz"}:
        if name != path.stem:
            raise ValueError(f"This compressed file contains one entry: {path.stem}")
        opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[format_]
        with opener(path, "rb") as source:
            _copy(source, target, limit)
    else:
        raise ValueError("member is only supported for containers and email attachments")
    return name


class _ByteSource(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def _copy(source: _ByteSource, target: IO[bytes], limit: int) -> None:
    remaining = limit
    while data := source.read(min(65536, remaining + 1)):
        remaining -= len(data)
        if remaining < 0:
            raise ValueError("Container entry exceeds max_expanded_bytes")
        target.write(data)


def _safe_member(name: str) -> None:
    normalized = name.replace("\\", "/")
    if (
        "\0" in name
        or PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(name).drive
        or ".." in PurePosixPath(normalized).parts
    ):
        raise ValueError("Container member must be a relative path without traversal")


def _tar_entries(archive: tarfile.TarFile, limit: int) -> Iterator[tarfile.TarInfo]:
    expanded = 0
    for entry in archive:
        expanded += entry.size
        if expanded > limit:
            raise ValueError("Expanded TAR content exceeds max_expanded_bytes")
        yield entry


def _copy_message(path: Path, format_: str, name: str, target: IO[bytes], limit: int) -> str:
    if format_ == "mbox":
        if not name.startswith("#") or not name[1:].isdigit():
            raise ValueError("Select an mbox message using member='#1', '#2', etc.")
        archive = mailbox.mbox(path, create=False)
        try:
            keys = list(archive.keys())
            index = int(name[1:]) - 1
            if not 0 <= index < len(keys):
                raise ValueError("Unknown message number")
            data = archive[keys[index]].as_bytes()
        finally:
            archive.close()
        filename = name[1:] + ".eml"
    else:
        with path.open("rb") as stream:
            message = BytesParser(policy=policy.default).parse(stream)
        entries = list(message.iter_attachments())
        matches = [
            (index, part)
            for index, part in enumerate(entries, 1)
            if name in (part.get_filename() or f"attachment-{index}", f"#{index}")
        ]
        if len(matches) != 1:
            raise ValueError("Attachment was not found or its name is ambiguous; use its #number")
        index, part = matches[0]
        data = part.get_payload(decode=True)
        if data is None and part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload and isinstance(payload[0], Message):
                data = payload[0].as_bytes()
        if not isinstance(data, bytes):
            raise ValueError("Attachment has no readable payload")
        filename = part.get_filename() or f"attachment-{index}"
        _safe_member(filename)
    if len(data) > limit:
        raise ValueError("Container entry exceeds max_expanded_bytes")
    target.write(data)
    return filename
