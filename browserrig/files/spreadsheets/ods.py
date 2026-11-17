from collections.abc import Iterator

from odf import teletype
from odf.opendocument import load as load_odf
from openpyxl.utils.cell import get_column_letter

from browserrig.files.content import ParsedContent, ReadContext

from .selection import CellRange, parse_bounds


def read_ods(context: ReadContext) -> ParsedContent:
    document = load_odf(str(context.path))
    tables = [
        node for node in document.spreadsheet.childNodes if node.qname[1] == "table"
    ]
    names = tuple(table.getAttribute("name") for table in tables)
    selected = context.request.sheet or names[0]
    if selected not in names:
        raise ValueError(f"Unknown sheet {selected!r}; available: {', '.join(names)}")
    details = ParsedContent(
        (), "ods", sheet=selected, sheets=names, cell_range=context.request.cell_range
    )

    def blocks() -> Iterator[str]:
        yield (
            "# Workbook\n\nSheets: "
            + ", ".join(names)
            + f"\n\n## Sheet: {selected}\n\n"
        )
        bounds = parse_bounds(context.request.cell_range, 1048576, 16384)
        yield from _odf_values(tables[names.index(selected)], bounds)

    details.blocks = blocks()
    details.limitations.append(
        "Stored values and formulas only; formatting, images and charts are not extracted"
    )
    return details


def _odf_values(table, bounds: CellRange) -> Iterator[str]:
    index = 0
    for row in _odf_rows(table):
        repeats = int(row.getAttribute("numberrowsrepeated") or 1)
        if not 1 <= repeats <= 1048576 or index + repeats > 1048576:
            raise ValueError("ODS row repetition exceeds spreadsheet dimensions")
        cells = _odf_cells(row)
        first, last = max(index + 1, bounds.top), min(index + repeats, bounds.bottom)
        index += repeats
        if any(cells):
            for number in range(first, last + 1):
                yield from _odf_row_text(
                    row, cells, number, left=bounds.left, right=bounds.right
                )
        if index >= bounds.bottom:
            return


def _odf_rows(table) -> Iterator:
    for node in table.childNodes:
        tag = getattr(node, "qname", (None, None))[1]
        if tag == "table-row":
            yield node
        elif tag in {"table-rows", "table-header-rows", "table-row-group"}:
            yield from _odf_rows(node)


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


def _odf_row_text(
    row, cells: list[str], number: int, *, left: int, right: int
) -> Iterator[str]:
    yield f"### Row {number}\n\n"
    if row.getAttribute("visibility") in {"collapse", "filter"}:
        yield "Hidden row (included).\n\n"
    for column, value in enumerate(cells, 1):
        if left <= column <= right and value:
            yield f"{get_column_letter(column)}{number}: {value}\n\n"
