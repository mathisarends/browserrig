import csv
from collections.abc import Iterable
from contextlib import suppress

from browserrig.files.content import ParsedContent, ReadContext
from browserrig.files.text import text_encoding

from .selection import parse_bounds
from .table import format_value, table_header


def read_delimited(context: ReadContext) -> ParsedContent:
    with context.path.open("rb") as source:
        sample = source.read(65536)
    encoding = text_encoding(sample)
    if encoding is None:
        raise ValueError("Cannot determine the table's text encoding")
    delimiter = "\t" if context.path.suffix.lower() == ".tsv" else ","
    if delimiter == ",":
        with suppress(csv.Error):
            delimiter = (
                csv.Sniffer()
                .sniff(sample.decode(encoding, errors="ignore"), delimiters=",;\t|")
                .delimiter
            )
    if context.request.sheet not in {None, "Data"}:
        raise ValueError("Delimited files have one sheet: Data")
    details = ParsedContent(
        (), context.path.suffix.lower().lstrip("."), sheet="Data", sheets=("Data",)
    )

    def blocks() -> Iterable[str]:
        with context.path.open(encoding=encoding, newline="") as source:
            rows = csv.reader(source, delimiter=delimiter)
            bounds = (
                parse_bounds(context.request.cell_range, 1048576, 1)
                if context.request.cell_range
                else None
            )
            for index, row in enumerate(rows, 1):
                if bounds and index > bounds.bottom:
                    break
                if bounds and index < bounds.top:
                    continue
                left, right = (bounds.left, bounds.right) if bounds else (1, len(row))
                if index == (bounds.top if bounds else 1):
                    yield table_header(left, right)
                cells = _delimited_cells(row, left, right)
                yield "| " + str(index) + " | " + " | ".join(cells) + " |\n"

    details.blocks = blocks()
    return details


def _delimited_cells(row: list[str], left: int, right: int) -> list[str]:
    """Format the selected columns, padding fields absent from a short CSV row."""
    cells = []
    for column in range(left - 1, right):
        if column < len(row):
            cells.append(format_value(row[column]))
        else:
            cells.append("")
    return cells
