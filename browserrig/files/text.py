import codecs
from pathlib import Path

from charset_normalizer import from_bytes

from .models import FileContent


def text_encoding(sample: bytes) -> str | None:
    for marker, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    ):
        if sample.startswith(marker):
            return encoding
    if b"\0" in sample:
        return None
    if (
        sample
        and sum(byte < 32 and byte not in (9, 10, 12, 13) for byte in sample) > len(sample) / 50
    ):
        return None
    try:
        codecs.getincrementaldecoder("utf-8")(errors="strict").decode(sample, final=False)
        return "utf-8-sig"
    except UnicodeError:
        match = from_bytes(sample).best()
        return match.encoding if match is not None and match.chaos < 0.1 else None


def read_text(path: Path, encoding: str, offset: int, max_chars: int) -> str:
    try:
        with path.open(encoding=encoding, newline="") as stream:
            remaining = offset
            while remaining:
                chunk = stream.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
            text = stream.read(max_chars + 1)
    except UnicodeError as error:
        raise ValueError(f"Cannot decode this file as {encoding}") from error
    if "\0" in text:
        raise ValueError("The file contains binary data, not readable text")
    return text


def text_result(path: Path, encoding: str, offset: int, max_chars: int) -> FileContent:
    text = read_text(path, encoding, offset, max_chars)
    return FileContent(
        path=str(path),
        media_type="text/plain",
        text=text[:max_chars],
        offset=offset,
        next_offset=offset + max_chars if len(text) > max_chars else None,
        encoding=encoding,
        size=path.stat().st_size,
    )
