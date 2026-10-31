from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import FileContent, FileReadStatus


@dataclass(frozen=True)
class ReadRequest:
    page_number: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    member: str | None = None
    ocr: bool | None = None


@dataclass
class ParsedContent:
    blocks: Iterable[str]
    format: str
    limitations: list[str] = field(default_factory=list)
    status: FileReadStatus = "complete"
    page_number: int | None = None
    page_count: int | None = None
    sheet: str | None = None
    sheets: tuple[str, ...] = ()
    cell_range: str | None = None
    entry_count: int | None = None

    def result(self, **fields) -> FileContent:
        return FileContent(
            format=self.format,
            status="partial"
            if self.status == "complete" and self.limitations
            else self.status,
            limitations=tuple(dict.fromkeys(self.limitations)),
            page_number=self.page_number,
            page_count=self.page_count,
            sheet=self.sheet,
            sheets=self.sheets,
            cell_range=self.cell_range,
            entry_count=self.entry_count,
            **fields,
        )


def cell_text(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r", "")
        .replace("\n", "<br>")
    )
