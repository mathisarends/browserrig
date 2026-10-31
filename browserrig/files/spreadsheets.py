import csv
import posixpath
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, suppress
from datetime import date, datetime, time
from pathlib import Path
from zipfile import ZipFile

import xlrd
from defusedxml.ElementTree import iterparse, parse
from odf import teletype
from odf.opendocument import load as load_odf
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter, range_boundaries

from .content import ParsedContent, ReadRequest, cell_text
from .text import text_encoding
from .xlsx import value_source


def read_xlsx(path: Path, request: ReadRequest) -> ParsedContent:
    extension = path.suffix.lower().lstrip(".")
    details = ParsedContent(
        (), extension if extension in {"xlsx", "xlsm", "xltx", "xltm"} else "xlsx"
    )

    def blocks() -> Iterator[str]:
        with ExitStack() as stack:
            source = stack.enter_context(value_source(path))
            book = load_workbook(
                source, read_only=True, data_only=False, keep_links=False
            )
            stack.callback(book.close)
            values = load_workbook(
                source, read_only=True, data_only=True, keep_links=False
            )
            stack.callback(values.close)
            details.sheets = tuple(book.sheetnames)
            selected = request.sheet or book.sheetnames[0]
            if selected not in book.sheetnames:
                raise ValueError(
                    f"Unknown sheet {selected!r}; available: {', '.join(book.sheetnames)}"
                )
            sheet = book[selected]
            cached = values[selected]
            details.sheet = selected
            notes, row_count, column_count = _xlsx_layout(path, selected)
            selection = request.cell_range
            if selection is None and row_count * column_count > 2_000_000:
                selection = f"A1:{get_column_letter(min(column_count, 64))}{min(row_count, 200)}"
                extent = f"{get_column_letter(column_count)}{row_count}"
                details.limitations.append(
                    f"Large or sparse sheet extends to {extent}; "
                    f"initial view is {selection}. Use cell_range to read any other area"
                )
            left, top, right, bottom = _bounds(selection, row_count, column_count)
            details.cell_range = (
                f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"
            )
            yield "# Workbook\n\nSheets: " + ", ".join(book.sheetnames) + "\n\n"
            yield f"## Sheet: {selected}\n\nRange: {details.cell_range}\n\n"
            for item in book:
                if item.sheet_state != "visible":
                    yield f"Sheet {item.title}: {item.sheet_state}\n\n"
            yield from notes
            yield _table_header(left, right)
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
                if request.cell_range is None and all(
                    cell.value is None for cell in row
                ):
                    continue
                cells = []
                for cell, saved in zip(row, cached_row, strict=True):
                    value = _value(cell.value)
                    if cell.data_type == "f":
                        has_formulas = True
                        value += (
                            " [stored result: "
                            + (
                                _value(saved.value)
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


def read_xls(path: Path, request: ReadRequest) -> ParsedContent:
    details = ParsedContent((), "xls")

    def blocks() -> Iterator[str]:
        book = xlrd.open_workbook(str(path), on_demand=True, formatting_info=True)
        try:
            details.sheets = tuple(book.sheet_names())
            selected = request.sheet or details.sheets[0]
            if selected not in details.sheets:
                raise ValueError(
                    f"Unknown sheet {selected!r}; available: {', '.join(details.sheets)}"
                )
            sheet = book.sheet_by_name(selected)
            details.sheet = selected
            left, top, right, bottom = _bounds(
                request.cell_range, sheet.nrows, sheet.ncols
            )
            details.cell_range = (
                f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}"
            )
            yield "# Workbook\n\nSheets: " + ", ".join(details.sheets) + "\n\n"
            yield f"## Sheet: {selected}\n\nRange: {details.cell_range}\n\n"
            if sheet.visibility:
                yield "This sheet is hidden.\n\n"
            for rlo, rhi, clo, chi in sheet.merged_cells:
                first = f"{get_column_letter(clo + 1)}{rlo + 1}"
                yield f"Merged cells: {first}:{get_column_letter(chi)}{rhi}\n\n"
            yield _table_header(left, right)
            for index in range(top, min(bottom, sheet.nrows) + 1):
                cells = []
                for column in range(left - 1, right):
                    cell = (
                        sheet.cell(index - 1, column) if column < sheet.ncols else None
                    )
                    cells.append(_value(_xls_value(cell, book.datemode)))
                yield "| " + str(index) + " | " + " | ".join(cells) + " |\n"
            details.limitations.append(
                "Stored values only; formulas, cell formatting, images and charts are not extracted"
            )
        finally:
            book.release_resources()

    details.blocks = blocks()
    return details


def read_ods(path: Path, request: ReadRequest) -> ParsedContent:
    document = load_odf(str(path))
    tables = [
        node for node in document.spreadsheet.childNodes if node.qname[1] == "table"
    ]
    names = tuple(table.getAttribute("name") for table in tables)
    selected = request.sheet or names[0]
    if selected not in names:
        raise ValueError(f"Unknown sheet {selected!r}; available: {', '.join(names)}")
    details = ParsedContent(
        (), "ods", sheet=selected, sheets=names, cell_range=request.cell_range
    )

    def blocks() -> Iterator[str]:
        yield (
            "# Workbook\n\nSheets: "
            + ", ".join(names)
            + f"\n\n## Sheet: {selected}\n\n"
        )
        bounds = _bounds(request.cell_range, 1048576, 16384)
        yield from _odf_values(tables[names.index(selected)], bounds)

    details.blocks = blocks()
    details.limitations.append(
        "Stored values and formulas only; formatting, images and charts are not extracted"
    )
    return details


def read_delimited(path: Path, request: ReadRequest) -> ParsedContent:
    with path.open("rb") as source:
        sample = source.read(65536)
    encoding = text_encoding(sample)
    if encoding is None:
        raise ValueError("Cannot determine the table's text encoding")
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    if delimiter == ",":
        with suppress(csv.Error):
            delimiter = (
                csv.Sniffer()
                .sniff(sample.decode(encoding, errors="ignore"), delimiters=",;\t|")
                .delimiter
            )
    if request.sheet not in {None, "Data"}:
        raise ValueError("Delimited files have one sheet: Data")
    details = ParsedContent(
        (), path.suffix.lower().lstrip("."), sheet="Data", sheets=("Data",)
    )

    def blocks() -> Iterable[str]:
        with path.open(encoding=encoding, newline="") as source:
            rows = csv.reader(source, delimiter=delimiter)
            bounds = (
                _bounds(request.cell_range, 1048576, 1) if request.cell_range else None
            )
            for index, row in enumerate(rows, 1):
                if bounds and index > bounds[3]:
                    break
                if bounds and index < bounds[1]:
                    continue
                left, right = (bounds[0], bounds[2]) if bounds else (1, len(row))
                if index == (bounds[1] if bounds else 1):
                    yield _table_header(left, right)
                cells = [
                    _value(row[column]) if column < len(row) else ""
                    for column in range(left - 1, right)
                ]
                yield "| " + str(index) + " | " + " | ".join(cells) + " |\n"

    details.blocks = blocks()
    return details


def _bounds(
    selection: str | None, rows: int, columns: int
) -> tuple[int, int, int, int]:
    if selection is None:
        return 1, 1, max(1, columns), max(1, rows)
    try:
        bounds = range_boundaries(selection.upper())
        left, top, right, bottom = bounds
        if any(value is None for value in bounds) or min(bounds) < 1:
            raise ValueError
        if right < left or bottom < top or right > 16384 or bottom > 1048576:
            raise ValueError
        return left, top, right, bottom
    except (ValueError, TypeError) as error:
        raise ValueError(
            "cell_range must be an A1 range, for example B2:F100"
        ) from error


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return cell_text(value)


def _table_header(left: int, right: int) -> str:
    columns = ["Row", *(get_column_letter(index) for index in range(left, right + 1))]
    return (
        "| "
        + " | ".join(columns)
        + " |\n| "
        + " | ".join("---" for _ in columns)
        + " |\n"
    )


def _xlsx_layout(path: Path, name: str) -> tuple[list[str], int, int]:
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
    return notes, max_row, max_column


def _xls_value(cell, datemode: int) -> object:
    if cell is None:
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        return xlrd.xldate_as_datetime(cell.value, datemode)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(cell.value, "Unknown cell error")
    return cell.value


def _odf_rows(table) -> Iterator:
    for node in table.childNodes:
        tag = getattr(node, "qname", (None, None))[1]
        if tag == "table-row":
            yield node
        elif tag in {"table-rows", "table-header-rows", "table-row-group"}:
            yield from _odf_rows(node)


def _odf_cell_text(cell) -> str:
    value = teletype.extractText(cell)
    if cell.qname[1] != "table-cell":
        return value
    if not value:
        attributes = ("value", "datevalue", "timevalue", "booleanvalue", "stringvalue")
        value = next(
            (
                str(stored)
                for name in attributes
                if (stored := cell.getAttribute(name)) is not None
            ),
            "",
        )
    formula = cell.getAttribute("formula")
    if formula:
        value += f" [formula: {formula}]"
    colspan = int(cell.getAttribute("numbercolumnsspanned") or 1)
    rowspan = int(cell.getAttribute("numberrowsspanned") or 1)
    if colspan > 1 or rowspan > 1:
        value += f" [merged: {colspan} columns × {rowspan} rows]"
    return value


def _odf_cells(row) -> list[str]:
    cells = []
    for cell in row.childNodes:
        tag = getattr(cell, "qname", (None, None))[1]
        if tag not in {"table-cell", "covered-table-cell"}:
            continue
        count = int(cell.getAttribute("numbercolumnsrepeated") or 1)
        if not 1 <= count <= 16384 or len(cells) + count > 16384:
            raise ValueError("ODS column repetition exceeds spreadsheet dimensions")
        cells.extend([_odf_cell_text(cell)] * count)
    return cells


def _odf_row_text(
    row, cells: list[str], number: int, left: int, right: int
) -> Iterator[str]:
    yield f"### Row {number}\n\n"
    if row.getAttribute("visibility") in {"collapse", "filter"}:
        yield "Hidden row (included).\n\n"
    yield "".join(
        f"{get_column_letter(column)}{number}: {value}\n\n"
        for column, value in enumerate(cells, 1)
        if left <= column <= right and value
    )


def _odf_values(table, bounds: tuple[int, int, int, int]) -> Iterator[str]:
    index = 0
    for row in _odf_rows(table):
        repeats = int(row.getAttribute("numberrowsrepeated") or 1)
        if not 1 <= repeats <= 1048576 or index + repeats > 1048576:
            raise ValueError("ODS row repetition exceeds spreadsheet dimensions")
        cells = _odf_cells(row)
        first, last = max(index + 1, bounds[1]), min(index + repeats, bounds[3])
        index += repeats
        if any(cells):
            for number in range(first, last + 1):
                yield from _odf_row_text(row, cells, number, bounds[0], bounds[2])
        if index >= bounds[3]:
            return
