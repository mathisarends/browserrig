from collections.abc import Iterator

import xlrd
from openpyxl.utils.cell import get_column_letter

from browserrig.files.content import ParsedContent, ReadContext

from .selection import parse_bounds
from .table import format_value, table_header


def read_xls(context: ReadContext) -> ParsedContent:
    details = ParsedContent((), "xls")

    def blocks() -> Iterator[str]:
        book = xlrd.open_workbook(
            str(context.path), on_demand=True, formatting_info=True
        )
        try:
            details.sheets = tuple(book.sheet_names())
            selected = context.request.sheet or details.sheets[0]
            if selected not in details.sheets:
                raise ValueError(
                    f"Unknown sheet {selected!r}; available: {', '.join(details.sheets)}"
                )
            sheet = book.sheet_by_name(selected)
            details.sheet = selected
            left, top, right, bottom = parse_bounds(
                context.request.cell_range, sheet.nrows, sheet.ncols
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
            yield table_header(left, right)
            for index in range(top, min(bottom, sheet.nrows) + 1):
                cells = []
                for column in range(left - 1, right):
                    cell = (
                        sheet.cell(index - 1, column) if column < sheet.ncols else None
                    )
                    cells.append(format_value(_xls_value(cell, book.datemode)))
                yield "| " + str(index) + " | " + " | ".join(cells) + " |\n"
            details.limitations.append(
                "Stored values only; formulas, cell formatting, images and charts are not extracted"
            )
        finally:
            book.release_resources()

    details.blocks = blocks()
    return details


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
