"""Preserve source identity and semantic containers until observation rendering."""

from bisect import bisect_right
from collections import defaultdict

from browserrig.core import Bounds, FrameTransform
from browserrig.observation.models import (
    ContentGroup,
    ContentNode,
    Element,
    ElementRef,
    Heading,
    TextBlock,
)

from . import semantics
from .document import Document, clean
from .styles import Style

_CONTAINERS = frozenset(
    {
        "banner",
        "navigation",
        "main",
        "complementary",
        "contentinfo",
        "search",
        "region",
        "dialog",
        "alertdialog",
        "form",
        "group",
        "radiogroup",
        "menu",
        "menubar",
        "tablist",
        "toolbar",
        "list",
        "listitem",
        "table",
        "row",
        "cell",
        "columnheader",
        "rowheader",
        "article",
    }
)
_TAG_ROLES = {
    "p": "paragraph",
    "blockquote": "blockquote",
    "pre": "preformatted",
    "article": "article",
    "section": "region",
    "tr": "row",
    "td": "cell",
    "th": "columnheader",
    "dl": "list",
    "dt": "listitem",
    "dd": "listitem",
}


class TextCollector:
    """Coalesce adjacent inline runs; represented source subtrees are omitted once."""

    def __init__(
        self,
        document: Document,
        elements: list[tuple[int, Element]],
        headings: list[tuple[int, Heading]],
        limit: int,
    ) -> None:
        self._document = document
        self._limit = limit
        self._excluded = _represented(document, elements, headings)
        links = {
            node: ElementRef(ref=element.ref)
            for node, element in elements
            if element.role == "link"
        }
        self._links: list[ElementRef | None] = []
        for node in document.elements():
            parent = document.parent(node)
            inherited = self._links[parent] if parent >= 0 else None
            self._links.append(links.get(node, inherited))
        self._breaks = sorted(
            {node for node, _ in (*elements, *headings)}
            | {node for node in document.elements() if document.tag(node) == "br"}
        )
        self._blocks: list[tuple[int, TextBlock]] = []
        self._owners: dict[int, int] = {}
        self._owner = -1
        self._previous = -1
        self._parts: list[str] = []
        self._block: TextBlock | None = None
        self._start = -1
        self._lengths: dict[str, int] = defaultdict(int)
        self._omitted: set[str] = set()

    def add(self, node: int, raw: str, block: TextBlock) -> None:
        block = block.model_copy(update={"control": self._links[node]})
        position = block.outside_viewport or "visible"
        if self._excluded[node]:
            self._flush()
            return
        if self._lengths[position] > self._limit:
            self._flush()
            if position not in self._omitted:
                self._blocks.append(
                    (node, block.model_copy(update={"truncated": True}))
                )
                self._omitted.add(position)
            return
        owner = self._block_owner(node)
        boundary = bisect_right(self._breaks, self._previous) != bisect_right(
            self._breaks, node
        )
        if (
            owner != self._owner
            or boundary
            or self._block is not None
            and (
                self._block.outside_viewport != block.outside_viewport
                or self._block.control != block.control
            )
        ):
            self._flush()
        if self._block is None:
            self._start = node
            self._owner = owner
            self._block = block
        else:
            self._parts.append(self._document.text_gap(self._previous, node))
            self._block = self._block.model_copy(
                update={"bounds": _union(self._block.bounds, block.bounds)}
            )
        remaining = max(0, self._limit + 1 - self._lengths[position])
        self._parts.append(raw[:remaining])
        if len(raw) > remaining:
            self._block = self._block.model_copy(update={"truncated": True})
        self._lengths[position] += len(raw[:remaining])
        self._previous = node

    def finish(self) -> list[tuple[int, TextBlock]]:
        self._flush()
        return self._blocks

    def _flush(self) -> None:
        if self._block is not None:
            raw = "".join(self._parts)
            preformatted = (
                self._document.tag(self._owner) == "pre" if self._owner >= 0 else False
            )
            value = (
                raw.strip()[: self._limit + 1]
                if preformatted
                else clean(raw, self._limit + 1)
            )
            if value:
                self._blocks.append(
                    (
                        self._start,
                        self._block.model_copy(
                            update={
                                "text": value,
                                "preformatted": preformatted,
                                "leading_space": bool(raw and raw[0].isspace()),
                                "trailing_space": bool(raw and raw[-1].isspace()),
                            }
                        ),
                    )
                )
        self._parts = []
        self._block = None

    def _block_owner(self, node: int) -> int:
        path: list[int] = []
        parent = self._document.parent(node)
        while parent >= 0 and parent not in self._owners:
            path.append(parent)
            display = self._document.style(parent, Style.DISPLAY)
            if display and not display.startswith("inline") and display != "contents":
                break
            parent = self._document.parent(parent)
        owner = self._owners.get(parent, parent)
        for ancestor in path:
            self._owners[ancestor] = owner
        return owner


def compose(
    document: Document,
    frame_id: str,
    entries: list[tuple[int, ContentNode]],
    transform: FrameTransform,
    links: frozenset[str],
) -> tuple[ContentNode, ...]:
    """Wrap ordered leaves in their actual semantic ancestors, dropping empty wrappers."""
    pending: dict[int, list[tuple[int, ContentNode]]] = defaultdict(list)
    for index, item in entries:
        pending[index].append((index, item))
    roots: list[ContentNode] = []
    for index in reversed(document.elements()):
        items = pending.pop(index, [])
        if not items:
            continue
        children = tuple(item for _, item in sorted(items, key=lambda item: item[0]))
        role = ""
        if document.is_element(index):
            semantic = semantics.role(document, index)
            role = (
                semantic
                if semantic in _CONTAINERS
                else _TAG_ROLES.get(document.tag(index), "")
            )
            if (
                not role
                and document.tag(index) == "div"
                and document.style(index, Style.DISPLAY) in {"block", "flow-root"}
                and _is_prose(children, links)
            ):
                role = "paragraph"
        if role:
            name = semantics.labelled_by(document, index) or clean(
                document.attributes(index).get("aria-label", ""), 80
            )
            if role == "group" and not name:
                name = semantics.name(document, index, role)
            children = (
                ContentGroup(
                    id=f"{frame_id}:{document.backend_ids[index]}",
                    role=role,
                    name=name,
                    bounds=_group_bounds(document, index, transform),
                    children=children,
                ),
            )
        parent = document.parent(index)
        if parent >= 0:
            pending[parent].extend((index, child) for child in children)
        else:
            roots.extend(children)
    return tuple(roots)


def _is_prose(children: tuple[ContentNode, ...], links: frozenset[str]) -> bool:
    return any(isinstance(child, TextBlock) for child in children) and all(
        isinstance(child, TextBlock)
        or isinstance(child, ElementRef)
        and child.ref in links
        for child in children
    )


def _group_bounds(
    document: Document, index: int, transform: FrameTransform
) -> Bounds | None:
    rect = document.rect(index)
    if rect is None:
        return None
    x, y = document.scroll
    return transform.bounds_to_viewport(
        Bounds(
            x=rect[0] - x,
            y=rect[1] - y,
            width=max(0, rect[2] - rect[0]),
            height=max(0, rect[3] - rect[1]),
        )
    )


def _represented(
    document: Document,
    elements: list[tuple[int, Element]],
    headings: list[tuple[int, Heading]],
) -> list[bool]:
    roots: set[int] = set()
    for node in document.elements():
        if document.tag(node) != "legend":
            continue
        parent = document.parent(node)
        if (
            parent >= 0
            and document.tag(parent) == "fieldset"
            and document.text(node, 10000) == semantics.name(document, parent, "group")
        ):
            roots.add(node)
    for node, heading in headings:
        if document.text(node, 10000) == heading.text:
            roots.add(node)
    for node, element in elements:
        if element.covered or element.role not in semantics.INTERACTIVE_ROLES:
            continue
        sources = [node, *document.labels(node)]
        sources.extend(
            target
            for reference in document.attributes(node)
            .get("aria-labelledby", "")
            .split()
            if (target := document.element_by_id(reference)) is not None
        )
        for source in sources:
            # Identity establishes ownership. Equality only checks that the complete
            # visible source is represented, rather than an abbreviated name.
            value = document.text(source, 10000)
            if value and (
                value == element.name
                and len(element.name) <= 100
                or value == element.value
                and len(value) <= 100
            ):
                roots.add(source)
    excluded = [False] * len(document)
    for index in document.elements():
        parent = document.parent(index)
        excluded[index] = index in roots or parent >= 0 and excluded[parent]
    return excluded


def _union(first: Bounds | None, second: Bounds | None) -> Bounds | None:
    if first is None or second is None:
        return first or second
    x, y = min(first.x, second.x), min(first.y, second.y)
    return Bounds(
        x=x,
        y=y,
        width=max(first.x + first.width, second.x + second.width) - x,
        height=max(first.y + first.height, second.y + second.height) - y,
    )
