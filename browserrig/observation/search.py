"""Search extracted page Markdown and return whole records rather than lines."""

import re
import unicodedata
from dataclasses import dataclass, field

from .content import PageContent

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
    content: PageContent, queries: tuple[str, ...], *, start: int, count: int
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


@dataclass
class _Parser:
    records: list[tuple[int, Record]] = field(default_factory=list)
    section: str = ""
    # The list the current items belong to, kept while sibling items follow.
    list_container: int = 0
    lines: int = 0
    items: list[_Item] = field(default_factory=list)
    paragraph: list[str] = field(default_factory=list)
    paragraph_start: int = 0
    table: list[str] = field(default_factory=list)
    fence: str = ""
    containers: int = 0

    def feed(self, line: str) -> None:
        self.lines += 1
        stripped = line.strip()
        if self.fence:
            self._text(line)
            if stripped.startswith(self.fence):
                self.fence = ""
            return
        if fence := _FENCE.match(line):
            self._end_table()
            self.fence = fence[1]
            self._text(line)
            return
        if stripped.startswith("|"):
            self._end_paragraph()
            self.table.append(stripped)
            return
        self._end_table()
        if not stripped:
            self._end_paragraph()
            return
        if heading := _HEADING.match(line):
            self._end_items()
            self.section = heading[1].strip()
            return
        if marker := _LIST_MARKER.match(line):
            self._end_paragraph()
            indent = len(marker[1])
            self._close_items(indent)
            if not self.list_container:
                self.list_container = self._container()
            self.items.append(
                _Item(
                    indent,
                    len(marker[0]),
                    [line.strip()],
                    self.list_container,
                    self.lines,
                )
            )
            return
        self._text(line)

    def close(self) -> None:
        self._end_table()
        self._end_paragraph()
        self._end_items()

    def _text(self, line: str) -> None:
        indent = len(line) - len(line.lstrip())
        while self.items and indent < self.items[-1].content:
            self._emit_item(self.items.pop())
        if self.items:
            self.items[-1].lines.append(line.strip())
        else:
            self.list_container = 0
            if not self.paragraph:
                self.paragraph_start = self.lines
            self.paragraph.append(line.strip())

    def _close_items(self, indent: int) -> None:
        while self.items and self.items[-1].indent >= indent:
            self._emit_item(self.items.pop())

    def _end_items(self) -> None:
        self._end_paragraph()
        self._close_items(0)
        self.list_container = 0

    def _emit_item(self, item: _Item) -> None:
        self._emit(" ".join(item.lines), container=item.container, order=item.order)

    def _end_paragraph(self) -> None:
        if self.paragraph:
            self._emit(
                " ".join(self.paragraph),
                container=self._container(),
                order=self.paragraph_start,
            )
            self.paragraph = []

    def _end_table(self) -> None:
        rows, self.table = self.table, []
        if not rows:
            return
        self._end_items()
        first = self.lines - len(rows)
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

    def _emit(self, text: str, *, container: int, order: int, header: str = "") -> None:
        self.records.append((order, Record(text, self.section, header, container)))

    def _container(self) -> int:
        self.containers += 1
        return self.containers


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
