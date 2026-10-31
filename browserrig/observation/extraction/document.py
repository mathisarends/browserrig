"""Index one DOMSnapshot document for fast queries by node index.

DOMSnapshot lists nodes in composed-tree pre-order, so every subtree is the
contiguous index range `index + 1 .. end(index)`. All inherited facts are computed
in one forward pass and all subtree queries are linear slices; nothing recurses.
"""

import re
from functools import cached_property

from cdpify.domains.domsnapshot import DocumentSnapshot, RareBooleanData, RareStringData

from .styles import Style

type Rect = tuple[float, float, float, float]
"""left, top, right, bottom in document CSS pixels."""

_ELEMENT, _TEXT = 1, 3
_WHITESPACE = re.compile(r"\s+")
# Icon-font glyphs sit in the Unicode Private Use Areas and read as nothing.
_ICON_GLYPHS = re.compile("[\ue000-\uf8ff\U000f0000-\U0010fffd]")
_UNBOUNDED = 1e9
_NO_TEXT = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "head",
        "title",
        "select",
        "option",
        "textarea",
    }
)
_LABELABLE = frozenset(
    {"input", "select", "textarea", "button", "meter", "output", "progress"}
)
_FORM_CONTROLS = frozenset({"input", "select", "textarea"})
_REPLACED = frozenset({"img", "svg", "input"})


def clean(text: str, limit: int = 150) -> str:
    return _WHITESPACE.sub(" ", _ICON_GLYPHS.sub("", text)).strip()[:limit]


def intersect(a: Rect, b: Rect | None) -> Rect:
    if b is None:
        return a
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def is_empty(rect: Rect) -> bool:
    return rect[2] - rect[0] < 1 or rect[3] - rect[1] < 1


class Document:  # pylint: disable=too-many-public-methods
    """Read-only view of one snapshot document.

    Bounds are document coordinates; `scroll` converts them to frame-local pixels.
    """

    def __init__(self, document: DocumentSnapshot, strings: list[str]) -> None:
        nodes, layout = document.nodes, document.layout
        # Chrome encodes empty strings as index -1, which now lands on this sentinel.
        strings = [*strings, ""]
        self.frame_id = strings[document.frame_id]
        self.url = (
            strings[document.document_url] if document.document_url is not None else ""
        )
        self.title = strings[document.title] if document.title is not None else ""
        self.scroll = (document.scroll_offset_x or 0.0, document.scroll_offset_y or 0.0)
        self.content_height = document.content_height or 0.0
        self.backend_ids: list[int] = nodes.backend_node_id or []
        self.clickable = _flags(nodes.is_clickable)
        self.checked = _flags(nodes.input_checked)
        self.selected = _flags(nodes.option_selected)
        self._strings = strings
        self._string_ids: dict[str, int] | None = None
        self._types: list[int] = nodes.node_type or []
        self._tags = [strings[name].lower() for name in nodes.node_name or []]
        self._values: list[int] = nodes.node_value or []
        self._parents: list[int] = nodes.parent_index or []
        self._raw_attributes: list[list[int]] = nodes.attributes or []
        self._attributes: dict[int, dict[str, str]] = {}
        self._input_values = _values(nodes.input_value, strings)
        self._text_values = _values(nodes.text_value, strings)
        self._layout = {node: index for index, node in enumerate(layout.node_index)}
        self._bounds = layout.bounds
        self._styles = layout.styles
        self._paint = layout.paint_orders or []
        self._end = self._subtree_ends()
        self._inherit()

    def __len__(self) -> int:
        return len(self._types)

    # Structure

    def is_element(self, index: int) -> bool:
        return self._types[index] == _ELEMENT

    def tag(self, index: int) -> str:
        return self._tags[index]

    def parent(self, index: int) -> int:
        return self._parents[index]

    def end(self, index: int) -> int:
        """One past the last descendant of `index`."""
        return self._end[index]

    def contains(self, ancestor: int, other: int) -> bool:
        return ancestor < other < self._end[ancestor]

    def ancestors(self, index: int):
        parent = self._parents[index]
        while parent >= 0:
            yield parent
            parent = self._parents[parent]

    def descendants(self, index: int, tags: frozenset[str]) -> list[int]:
        return [
            node
            for node in range(index + 1, self._end[index])
            if self._types[node] == _ELEMENT and self._tags[node] in tags
        ]

    def elements(self) -> range:
        return range(len(self._types))

    # Attributes and values

    def attributes(self, index: int) -> dict[str, str]:
        cached = self._attributes.get(index)
        if cached is None:
            raw = (
                self._raw_attributes[index] if index < len(self._raw_attributes) else ()
            )
            strings = self._strings
            cached = {
                strings[raw[i]].lower(): strings[raw[i + 1]]
                for i in range(0, len(raw) - 1, 2)
            }
            self._attributes[index] = cached
        return cached

    def has_attribute(self, index: int, name: str) -> bool:
        """Cheap presence test on the raw string table, without building a dict."""
        key = self._string_id(name)
        if key is None or index >= len(self._raw_attributes):
            return False
        return key in self._raw_attributes[index][::2]

    def with_any_attribute(self, names: tuple[str, ...]) -> frozenset[int]:
        """Nodes carrying at least one of `names`, found in one scan of the raw table."""
        keys = {key for name in names if (key := self._string_id(name)) is not None}
        if not keys:
            return frozenset()
        return frozenset(
            index
            for index, raw in enumerate(self._raw_attributes)
            if raw and not keys.isdisjoint(raw[::2])
        )

    def input_value(self, index: int) -> str | None:
        return self._input_values.get(index, self._text_values.get(index))

    def element_by_id(self, element_id: str) -> int | None:
        return self._ids.get(element_id)

    def labels(self, control: int) -> list[int]:
        return self._labels.get(control, [])

    def linked_control(self, label: int) -> int | None:
        """The control a <label> activates: its `for` target or first form control inside."""
        target = self.attributes(label).get("for")
        if target is not None:
            control = self._ids.get(target)
            return (
                control
                if control is not None and self._tags[control] in _LABELABLE
                else None
            )
        controls = self.descendants(label, _FORM_CONTROLS)
        return controls[0] if controls else None

    # Layout

    def has_layout(self, index: int) -> bool:
        return index in self._layout

    def style(self, index: int, style: Style) -> str:
        layout = self._layout.get(index)
        if layout is None:
            return ""
        values = self._styles[layout]
        return self._strings[values[style.slot]] if len(values) > style.slot else ""

    def rect(self, index: int) -> Rect | None:
        """The layout box, or the union of descendant boxes for empty inline wrappers."""
        layout = self._layout.get(index)
        if layout is None:
            return None
        x, y, width, height = self._bounds[layout]
        rect = (x, y, x + width, y + height)
        if not is_empty(rect):
            return rect
        union: Rect | None = None
        for node in range(index + 1, min(self._end[index], index + 200)):
            child = self._layout.get(node)
            if child is None:
                continue
            x, y, width, height = self._bounds[child]
            if width >= 1 and height >= 1:
                box = (x, y, x + width, y + height)
                union = (
                    box
                    if union is None
                    else (
                        min(union[0], box[0]),
                        min(union[1], box[1]),
                        max(union[2], box[2]),
                        max(union[3], box[3]),
                    )
                )
        return union or rect

    def paint_order(self, index: int) -> int:
        layout = self._layout.get(index)
        return (
            self._paint[layout]
            if layout is not None and layout < len(self._paint)
            else -1
        )

    def hidden(self, index: int) -> bool:
        """Inherited invisibility: opacity 0, `inert`, or a hidden ancestor."""
        return self._hidden[index]

    def pinned(self, index: int) -> bool:
        """Inside a fixed or sticky box, so scrolling the page does not move it."""
        return self._pinned[index]

    def clip(self, index: int) -> Rect | None:
        """Visible area allowed by `overflow: hidden|clip` ancestors."""
        return self._clip[index]

    def scroll_clip(self, index: int) -> Rect | None:
        """Visible area of `overflow: auto|scroll` ancestors; content beyond needs scrolling."""
        return self._scroll_clip[index]

    # Text

    def text(self, index: int, limit: int = 150) -> str:
        """Rendered text in document order; labelled or replaced descendants use their name.

        Text nodes keep their own whitespace, so inline boundaries such as `<wbr>` or
        styled spans do not split words; block-level boxes are separated by a space.
        """
        parts: list[str] = []
        length = 0
        node, stop = index + 1, self._end[index]
        types, tags, layout = self._types, self._tags, self._layout
        while node < stop and length < limit:
            kind = types[node]
            if kind == _TEXT:
                if node in layout:
                    value = self._strings[self._values[node]]
                    parts.append(value)
                    length += len(value)
                node += 1
                continue
            if kind != _ELEMENT:
                node += 1
                continue
            tag = tags[node]
            if self._hidden[node] or tag in _NO_TEXT or node in self._aria_hidden:
                node = self._end[node]
                continue
            alternative = self._replacement_text(node, tag)
            if alternative is not None:
                if alternative:
                    parts.append(f" {alternative} ")
                    length += len(alternative) + 2
                node = self._end[node]
                continue
            if tag == "br" or (node in layout and not self._inline(node)):
                parts.append(" ")
            node += 1
        return clean("".join(parts), limit)

    def own_text(self, index: int, limit: int = 150) -> str:
        """All text nodes, rendered or not, for option labels inside closed selects."""
        return clean(
            "".join(
                self._strings[self._values[node]]
                for node in range(index + 1, self._end[index])
                if self._types[node] == _TEXT
            ),
            limit,
        )

    def text_runs(self) -> list[tuple[int, str, Rect]]:
        """Every rendered, visible text node with its parent element and box."""
        runs: list[tuple[int, str, Rect]] = []
        for node, layout in self._layout.items():
            if self._types[node] != _TEXT:
                continue
            parent = self._parents[node]
            if parent < 0 or self._hidden[parent] or self._tags[parent] in _NO_TEXT:
                continue
            if self.style(parent, Style.VISIBILITY) not in ("", "visible"):
                continue
            value = clean(self._strings[self._values[node]], 1000)
            x, y, width, height = self._bounds[layout]
            if value and width >= 1 and height >= 1:
                runs.append((node, value, (x, y, x + width, y + height)))
        runs.sort()
        return runs

    def _inline(self, index: int) -> bool:
        return self.style(index, Style.DISPLAY).startswith("inline")

    def _replacement_text(self, node: int, tag: str) -> str | None:
        if tag in _REPLACED and node not in self._layout:
            return ""
        attributes = self.attributes(node)
        label = attributes.get("aria-label")
        if label is not None:
            return clean(label)
        if tag == "img" or (tag == "input" and attributes.get("type") == "image"):
            return clean(attributes.get("alt", ""))
        if tag == "svg":
            titles = self.descendants(node, frozenset({"title"}))
            return self.own_text(titles[0]) if titles else ""
        return None

    # Precomputation

    def _string_id(self, value: str) -> int | None:
        if self._string_ids is None:
            self._string_ids = {
                string: index for index, string in enumerate(self._strings)
            }
        return self._string_ids.get(value)

    @cached_property
    def _aria_hidden(self) -> frozenset[int]:
        return frozenset(
            index
            for index in self.with_any_attribute(("aria-hidden",))
            if self.attributes(index).get("aria-hidden", "").lower() == "true"
        )

    @cached_property
    def _ids(self) -> dict[str, int]:
        key = self._string_id("id")
        if key is None:
            return {}
        strings, ids = self._strings, {}
        for index, raw in enumerate(self._raw_attributes):
            for position in range(0, len(raw) - 1, 2):
                if raw[position] == key:
                    ids.setdefault(strings[raw[position + 1]], index)
                    break
        return ids

    @cached_property
    def _labels(self) -> dict[int, list[int]]:
        labels: dict[int, list[int]] = {}
        for index, tag in enumerate(self._tags):
            if tag == "label" and self._types[index] == _ELEMENT:
                control = self.linked_control(index)
                if control is not None:
                    labels.setdefault(control, []).append(index)
        return labels

    def _subtree_ends(self) -> list[int]:
        parents = self._parents
        end = list(range(1, len(parents) + 1))
        for index in range(len(parents) - 1, -1, -1):
            parent = parents[index]
            if parent >= 0 and end[index] > end[parent]:
                end[parent] = end[index]
        return end

    def _inherit(self) -> None:
        count = len(self._types)
        parents, types, tags = self._parents, self._types, self._tags
        layout, styles, strings, bounds = (
            self._layout,
            self._styles,
            self._strings,
            self._bounds,
        )
        position_at, opacity_at = Style.POSITION.slot, Style.OPACITY.slot
        overflow_x_at, overflow_y_at = Style.OVERFLOW_X.slot, Style.OVERFLOW_Y.slot
        inert = self._string_id("inert")
        hidden, pinned = [False] * count, [False] * count
        clip: list[Rect | None] = [None] * count
        scroll: list[Rect | None] = [None] * count
        inner_clip: list[Rect | None] = [None] * count
        inner_scroll: list[Rect | None] = [None] * count
        for index in range(count):
            parent = parents[index]
            if parent >= 0:
                is_hidden, is_pinned = hidden[parent], pinned[parent]
                hard, soft = inner_clip[parent], inner_scroll[parent]
            else:
                is_hidden = is_pinned = False
                hard = soft = None
            own_hard, own_soft = hard, soft
            element = types[index] == _ELEMENT
            if element and not is_hidden and inert in self._raw_attributes[index][::2]:
                is_hidden = True
            box = layout.get(index) if element else None
            values = styles[box] if box is not None else ()
            if box is not None and len(values) > overflow_y_at:
                position = strings[values[position_at]]
                if position == "fixed":
                    hard = soft = own_hard = own_soft = None
                is_pinned = is_pinned or position in ("fixed", "sticky")
                is_hidden = is_hidden or strings[values[opacity_at]] == "0"
                overflow_x = strings[values[overflow_x_at]]
                overflow_y = strings[values[overflow_y_at]]
                if (overflow_x != "visible" or overflow_y != "visible") and tags[
                    index
                ] not in (
                    "html",
                    "body",
                ):
                    x, y, width, height = bounds[box]
                    rect = (x, y, x + width, y + height)
                    own_hard = intersect(
                        _overflow(rect, overflow_x, overflow_y, True), hard
                    )
                    own_soft = intersect(
                        _overflow(rect, overflow_x, overflow_y, False), soft
                    )
            hidden[index], pinned[index] = is_hidden, is_pinned
            clip[index], scroll[index] = hard, soft
            inner_clip[index], inner_scroll[index] = own_hard, own_soft
        self._hidden, self._pinned = hidden, pinned
        self._clip, self._scroll_clip = clip, scroll


def _overflow(rect: Rect, overflow_x: str, overflow_y: str, hard: bool) -> Rect:
    clips = ("hidden", "clip") if hard else ("auto", "scroll")
    clips_x, clips_y = overflow_x in clips, overflow_y in clips
    return (
        rect[0] if clips_x else -_UNBOUNDED,
        rect[1] if clips_y else -_UNBOUNDED,
        rect[2] if clips_x else _UNBOUNDED,
        rect[3] if clips_y else _UNBOUNDED,
    )


def _values(data: RareStringData | None, strings: list[str]) -> dict[int, str]:
    if data is None:
        return {}
    return {
        index: strings[value]
        for index, value in zip(data.index, data.value, strict=True)
    }


def _flags(data: RareBooleanData | None) -> frozenset[int]:
    return frozenset(data.index) if data is not None else frozenset()
