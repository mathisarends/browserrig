"""Search extracted page Markdown and return whole records rather than lines."""

import re
import unicodedata
from dataclasses import dataclass, field

from .content import ExtractedContent

# A record longer than this is shown as a window around its first match.
_RECORD_CHARS = 600
_LIST_MARKER = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_HEADING = re.compile(r"^#{1,6}\s+(.*)")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
# Link destinations are not visible text; matching ignores them.
_LINK = re.compile(r"!?\[([^\]]*)\]\((?:<[^>]*>|[^)\s]*)\)")
_SEPARATOR = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+$")


@dataclass(frozen=True, slots=True)
class Record:
    """A table row, list item or paragraph, with the context needed to read it alone."""

    text: str
    section: str = ""
    # The column header of the table this row belongs to.
    header: str = ""
    # Records sharing a container print their header once.
    container: int = -1


@dataclass(frozen=True, slots=True)
class PageSearch:
    url: str
    title: str
    queries: tuple[str, ...]
    total: int
    start: int
    records: tuple[Record, ...]
    limitations: tuple[str, ...] = field(default=())

    def render(self) -> str:
        shown = " | ".join(f'"{query}"' for query in self.queries)
        title = " ".join(self.title.split()) or "(untitled)"
        noun = "record matches" if self.total == 1 else "records match"
        lines = [f"{self.total} {noun} {shown} on {title} <{self.url}>"]
        section, container = None, None
        for record in self.records:
            if record.section != section:
                section = record.section
                if section:
                    lines.extend(("", f"## {section}"))
                container = None
            if record.container != container:
                container = record.container
                lines.append("")
                if record.header:
                    lines.append(record.header)
            lines.append(record.text)
        following = self.total - self.start - len(self.records)
        if self.start or following > 0:
            first = self.start + 1 if self.records else self.start
            lines.extend(
                (
                    "",
                    f"Showing records {first}-{self.start + len(self.records)} of "
                    f"{self.total}."
                    + (
                        f" {following} more; continue with start="
                        f"{self.start + len(self.records)} or narrow the query."
                        if following > 0
                        else ""
                    ),
                )
            )
        if self.limitations:
            lines.extend(("", "Search limitations:"))
            lines.extend(f"- {' '.join(item.split())}" for item in self.limitations)
        return "\n".join(lines)


def search_content(
    content: ExtractedContent, queries: tuple[str, ...], *, start: int, count: int
) -> PageSearch:
    """Records whose visible text contains any query, ignoring case and accents."""
    needles = tuple(dict.fromkeys(filter(None, map(_fold, queries))))
    if not needles:
        raise ValueError("Search needs visible query text")
    found = [
        record
        for record in records(content.markdown)
        if any(needle in _fold(_visible(record.text)) for needle in needles)
    ]
    selected = tuple(
        _window(record, needles) for record in found[start : start + count]
    )
    return PageSearch(
        url=content.url,
        title=content.title,
        queries=queries,
        total=len(found),
        start=start,
        records=selected,
        limitations=content.limitations,
    )


def records(markdown: str) -> list[Record]:
    """Split Markdown into table rows, innermost list items and paragraphs."""
    parser = _Parser()
    for line in markdown.splitlines():
        parser.feed(line)
    parser.close()
    # Nested items close before their parents; report records in page order.
    return [record for _, record in sorted(parser.records, key=lambda item: item[0])]


@dataclass
class _Item:
    indent: int
    content: int
    lines: list[str]
    container: int
    order: int


class _Parser:
    def __init__(self) -> None:
        self.records: list[tuple[int, Record]] = []
        self._section = ""
        # Keep the list's identity while sibling items follow.
        self._list_container = 0
        self._lines = 0
        self._items: list[_Item] = []
        self._paragraph: list[str] = []
        self._paragraph_start = 0
        self._table: list[str] = []
        self._fence = ""
        self._containers = 0

    def feed(self, line: str) -> None:
        self._lines += 1
        stripped = line.strip()
        if self._fence:
            self._text(line)
            if stripped.startswith(self._fence):
                self._fence = ""
            return
        if fence := _FENCE.match(line):
            self._end_table()
            self._fence = fence[1]
            self._text(line)
            return
        if stripped.startswith("|"):
            self._end_paragraph()
            self._table.append(stripped)
            return
        self._end_table()
        if not stripped:
            self._end_paragraph()
            return
        if heading := _HEADING.match(line):
            self._end_items()
            self._section = heading[1].strip()
            return
        if marker := _LIST_MARKER.match(line):
            self._end_paragraph()
            indent = len(marker[1])
            self._close_items(indent)
            if not self._list_container:
                self._list_container = self._container()
            self._items.append(
                _Item(
                    indent,
                    len(marker[0]),
                    [line.strip()],
                    self._list_container,
                    self._lines,
                )
            )
            return
        self._text(line)

    def close(self) -> None:
        self._end_table()
        self._end_paragraph()
        self._end_items()

    def _end_table(self) -> None:
        rows, self._table = self._table, []
        if not rows:
            return
        self._end_items()
        first = self._lines - len(rows)
        header = ""
        if len(rows) > 1 and _SEPARATOR.match(rows[1]):
            # An all-empty header row stands for a table without column headers.
            if rows[0].strip("| "):
                header = rows[0]
            rows = rows[2:]
        container = self._container()
        for offset, row in enumerate(rows):
            if row.strip("| "):
                self._emit(
                    row, header=header, container=container, order=first + offset
                )

    def _end_items(self) -> None:
        self._end_paragraph()
        self._close_items(0)
        self._list_container = 0

    def _text(self, line: str) -> None:
        indent = len(line) - len(line.lstrip())
        while self._items and indent < self._items[-1].content:
            self._emit_item(self._items.pop())
        if self._items:
            self._items[-1].lines.append(line.strip())
        else:
            self._list_container = 0
            if not self._paragraph:
                self._paragraph_start = self._lines
            self._paragraph.append(line.strip())

    def _close_items(self, indent: int) -> None:
        while self._items and self._items[-1].indent >= indent:
            self._emit_item(self._items.pop())

    def _emit_item(self, item: _Item) -> None:
        self._emit(" ".join(item.lines), container=item.container, order=item.order)

    def _end_paragraph(self) -> None:
        if self._paragraph:
            self._emit(
                " ".join(self._paragraph),
                container=self._container(),
                order=self._paragraph_start,
            )
            self._paragraph = []

    def _emit(self, text: str, *, container: int, order: int, header: str = "") -> None:
        self.records.append((order, Record(text, self._section, header, container)))

    def _container(self) -> int:
        self._containers += 1
        return self._containers


def _window(record: Record, needles: tuple[str, ...]) -> Record:
    text = record.text
    if len(text) <= _RECORD_CHARS:
        return record
    folded, offsets = _search_text(text)
    at = min((folded.find(needle) for needle in needles if needle in folded), default=0)
    at = offsets[at] if offsets else 0
    begin = max(0, min(at - _RECORD_CHARS // 3, len(text) - _RECORD_CHARS))
    end = begin + _RECORD_CHARS
    clipped = (
        ("…" if begin else "") + text[begin:end] + ("…" if end < len(text) else "")
    )
    return Record(clipped, record.section, record.header, record.container)


def _visible(text: str) -> str:
    return _LINK.sub(r"\1", text)


def _fold(text: str) -> str:
    """Case- and accent-insensitive with collapsed whitespace."""
    return _normalize(text, list(range(len(text))))[0]


def _search_text(text: str) -> tuple[str, list[int]]:
    """Visible search text with positions in the original Markdown."""
    visible, offsets = [], []
    start = 0
    for link in _LINK.finditer(text):
        visible.extend((text[start : link.start()], link[1]))
        offsets.extend(range(start, link.start()))
        offsets.extend(range(link.start(1), link.end(1)))
        start = link.end()
    visible.append(text[start:])
    offsets.extend(range(start, len(text)))
    return _normalize("".join(visible), offsets)


def _normalize(text: str, offsets: list[int]) -> tuple[str, list[int]]:
    folded, positions = [], []
    for char, offset in zip(text, offsets, strict=True):
        base = unicodedata.normalize("NFD", char)
        base = "".join(part for part in base if not unicodedata.combining(part))
        if not base:
            continue
        base = base.casefold()
        normalized = base[0] if len(base) == 1 else char.lower()[:1] or char
        if normalized.isspace():
            if not folded or folded[-1] == " ":
                continue
            normalized = " "
        folded.append(normalized)
        positions.append(offset)
    if folded and folded[-1] == " ":
        folded.pop()
        positions.pop()
    return "".join(folded), positions
