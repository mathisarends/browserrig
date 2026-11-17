from __future__ import annotations

import posixpath
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple
from zipfile import ZipFile

from defusedxml.ElementTree import iterparse, parse
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter

from browserrig.files.content import ParsedContent, ReadContext, cell_text
from browserrig.files.xlsx import value_source

from .selection import parse_bounds
from .table import format_value, table_header


def read_xlsx(context: ReadContext) -> ParsedContent:
    extension = context.path.suffix.lower().lstrip(".")
    details = ParsedContent(
        (), extension if extension in {"xlsx", "xlsm", "xltx", "xltm"} else "xlsx"
    )

    def blocks() -> Iterator[str]:
        with ExitStack() as stack:
            source = stack.enter_context(value_source(context.path))
            book = load_workbook(
                source, read_only=True, data_only=False, keep_links=False
            )
            stack.callback(book.close)
            values = load_workbook(
                source, read_only=True, data_only=True, keep_links=False
            )
            stack.callback(values.close)
            details.sheets = tuple(book.sheetnames)
            selected = context.request.sheet or book.sheetnames[0]
            if selected not in book.sheetnames:
                raise ValueError(
                    f"Unknown sheet {selected!r}; available: {', '.join(book.sheetnames)}"
                )
            sheet = book[selected]
            cached = values[selected]
            details.sheet = selected
            notes, row_count, column_count = _xlsx_layout(context.path, selected)
            selection = context.request.cell_range
            if selection is None and row_count * column_count > 2_000_000:
                selection = f"A1:{get_column_letter(min(column_count, 64))}{min(row_count, 200)}"
                extent = f"{get_column_letter(column_count)}{row_count}"
                details.limitations.append(
                    f"Large or sparse sheet extends to {extent}; "
                    f"initial view is {selection}. Use cell_range to read any other area"
                )
            left, top, right, bottom = parse_bounds(selection, row_count, column_count)
            details.cell_range = (
                f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"
            )
            yield "# Workbook\n\nSheets: " + ", ".join(book.sheetnames) + "\n\n"
            yield f"## Sheet: {selected}\n\nRange: {details.cell_range}\n\n"
            for item in book:
                if item.sheet_state != "visible":
                    yield f"Sheet {item.title}: {item.sheet_state}\n\n"
            yield from notes
            yield table_header(left, right)
            rows = sheet.iter_rows(
                min_row=top, max_row=bottom, min_col=left, max_col=right
            )
            cached_rows = cached.iter_rows(
                min_row=top, max_row=bottom, min_col=left, max_col=right
            )
            has_formulas = False
            for index, (row, cached_row) in enumerate(
                zip(rows, cached_rows, strict=True), top
            ):
                if context.request.cell_range is None and all(
                    cell.value is None for cell in row
                ):
                    continue
                cells = []
                for cell, saved in zip(row, cached_row, strict=True):
                    value = format_value(cell.value)
                    if cell.data_type == "f":
                        has_formulas = True
                        value += (
                            " [stored result: "
                            + (
                                format_value(saved.value)
                                if saved.value is not None
                                else "unavailable"
                            )
                            + "]"
                        )
                    if cell.value is not None and cell.number_format not in (
                        "General",
                        "@",
                    ):
                        value += f" [format: {cell_text(cell.number_format)}]"
                    cells.append(value)
                yield "| " + str(index) + " | " + " | ".join(cells) + " |\n"
            if has_formulas:
                details.limitations.append(
                    "Formulas were not recalculated; stored results can be missing or stale"
                )
            details.limitations.append(
                "Embedded images, charts and comments are not extracted"
            )
            details.limitations.append(
                "Conditional formatting is not applied to stored values"
            )

    details.blocks = blocks()
    return details


def _xlsx_layout(path: Path, name: str) -> _SheetLayout:
    notes = []
    max_row = max_column = 1
    row = column = 0
    has_content = False
    with ZipFile(path) as archive:
        with archive.open("xl/workbook.xml") as stream:
            book = parse(stream).getroot()
        relationship = next(
            node.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            for node in book.iter()
            if node.tag.endswith("}sheet") and node.get("name") == name
        )
        with archive.open("xl/_rels/workbook.xml.rels") as stream:
            target = next(
                node.attrib["Target"]
                for node in parse(stream).getroot()
                if node.get("Id") == relationship
            )
        target = (
            posixpath.normpath(posixpath.join("xl", target))
            if not target.startswith("/")
            else target[1:]
        )
        with archive.open(target) as stream:
            for event, node in iterparse(stream, events=("start", "end")):
                tag = node.tag.rsplit("}", 1)[-1]
                if event == "start":
                    if tag == "row":
                        row, column = int(node.get("r", row + 1)), 0
                    elif tag == "c":
                        coordinate = node.get("r")
                        row, column = (
                            coordinate_to_tuple(coordinate)
                            if coordinate
                            else (row, column + 1)
                        )
                        has_content = False
                    continue
                if tag in {"v", "f", "t"} and node.text is not None:
                    has_content = True
                if tag == "c" and has_content:
                    max_row, max_column = max(max_row, row), max(max_column, column)
                if tag == "mergeCell":
                    notes.append(f"Merged cells: {node.get('ref')}\n\n")
                elif tag == "row" and node.get("hidden") in {"1", "true"}:
                    notes.append(f"Hidden row: {row} (included in this read)\n\n")
                elif tag == "col" and node.get("hidden") in {"1", "true"}:
                    notes.append(
                        f"Hidden columns: {node.get('min')}–{node.get('max')} (included)\n\n"
                    )
                node.clear()
    return _SheetLayout(notes, max_row, max_column)


class _SheetLayout(NamedTuple):
    notes: list[str]
    rows: int
    columns: int
