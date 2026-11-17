from typing import NamedTuple

from openpyxl.utils.cell import range_boundaries


class CellRange(NamedTuple):
    """Inclusive 1-based column and row bounds of a sheet selection."""

    left: int
    top: int
    right: int
    bottom: int


def parse_bounds(selection: str | None, rows: int, columns: int) -> CellRange:
    if selection is None:
        return CellRange(1, 1, max(1, columns), max(1, rows))
    try:
        bounds = range_boundaries(selection.upper())
        left, top, right, bottom = bounds
        if any(value is None for value in bounds) or min(bounds) < 1:
            raise ValueError
        if right < left or bottom < top or right > 16384 or bottom > 1048576:
            raise ValueError
        return CellRange(left, top, right, bottom)
    except (ValueError, TypeError) as error:
        raise ValueError(
            "cell_range must be an A1 range, for example B2:F100"
        ) from error
