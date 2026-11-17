from datetime import date, datetime, time

from openpyxl.utils.cell import get_column_letter

from browserrig.files.content import cell_text


def table_header(left: int, right: int) -> str:
    columns = ["Row", *(get_column_letter(index) for index in range(left, right + 1))]
    return (
        "| "
        + " | ".join(columns)
        + " |\n| "
        + " | ".join("---" for _ in columns)
        + " |\n"
    )


def format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return cell_text(value)
