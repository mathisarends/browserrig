from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfileobj
from tempfile import SpooledTemporaryFile
from typing import IO
from xml.sax.saxutils import XMLGenerator
from zipfile import ZIP_DEFLATED, ZipFile

from defusedxml.sax import parse


class _WorksheetValues(XMLGenerator):
    def __init__(self, output) -> None:
        super().__init__(output, encoding="utf-8")
        self._skipped = 0

    def startElement(self, name, attrs):  # pylint: disable=invalid-name
        # Display rules from some producers are rejected even in read-only mode.
        if self._skipped or name.rsplit(":", 1)[-1] == "conditionalFormatting":
            self._skipped += 1
        else:
            super().startElement(name, attrs)

    def endElement(self, name):  # pylint: disable=invalid-name
        if self._skipped:
            self._skipped -= 1
        else:
            super().endElement(name)

    def characters(self, content):
        if not self._skipped:
            super().characters(content)


@contextmanager
def value_source(path: Path) -> Generator[IO[bytes], None, None]:
    # The spill is local and temporary; the original workbook is never rewritten.
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as buffer:
        with ZipFile(path) as source, ZipFile(buffer, "w", compression=ZIP_DEFLATED) as output:
            for entry in source.infolist():
                with source.open(entry) as input_, output.open(entry, "w") as target:
                    if entry.filename.startswith("xl/worksheets/") and entry.filename.endswith(
                        ".xml"
                    ):
                        parse(input_, _WorksheetValues(target))
                    else:
                        copyfileobj(input_, target, length=65536)
        buffer.seek(0)
        yield buffer
