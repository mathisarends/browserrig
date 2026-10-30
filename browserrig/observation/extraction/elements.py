"""Turn one indexed frame document into elements, headings, alerts and page text."""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

from browserrig.core.geometry import Bounds, FrameTransform

from ..models import Element, Heading, Modal
from . import semantics
from .document import Document, Rect, clean
from .styles import Style
from .visibility import Occlusion, hidden, visible_area

_SKIPPED_TAGS = frozenset(
    {"html", "body", "head", "script", "style", "noscript", "template", "iframe", "frame", "label"}
)
_NATIVE_TAGS = frozenset({"a", "button", "input", "select", "textarea", "summary"})
_HINT_ATTRIBUTES = (
    "role",
    "contenteditable",
    "aria-haspopup",
    "jsaction",
    "data-action",
    "ng-click",
    "data-toggle",
    "data-bs-toggle",
    "draggable",
    "tabindex",
)
_OPTION_PARENTS = frozenset({"select", "optgroup", "datalist"})
_DELEGATED = ("jsaction", "data-action", "ng-click", "data-toggle", "data-bs-toggle")
# Content blocks get tabindex for focus management, not because they are controls.
_CONTENT_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "main",
        "section",
        "article",
        "aside",
        "nav",
        "header",
        "footer",
        "form",
        "table",
        "ul",
        "ol",
        "dl",
        "pre",
        "blockquote",
        "figure",
    }
)
_LANDMARKS = {
    "banner": "HEADER",
    "navigation": "NAVIGATION",
    "main": "MAIN",
    "complementary": "SIDEBAR",
    "contentinfo": "FOOTER",
    "search": "SEARCH",
    "region": "SECTION",
    "dialog": "DIALOG",
    "alertdialog": "DIALOG",
}
_GROUPS = {
    "form": "form",
    "group": "group",
    "radiogroup": "radiogroup",
    "menu": "menu",
    "menubar": "menu",
    "tablist": "tabs",
    "toolbar": "toolbar",
}
_UNNAMED_GROUPS = frozenset({"form", "radiogroup", "menu", "tabs", "toolbar"})
_ALERT_ROLES = frozenset({"alert", "status"})

type Context = tuple[str, str]
"""Section and group labels that apply to a node's descendants."""


@dataclass(slots=True)
class FrameExtraction:
    """Results keyed by document order so frames can be merged into page order."""

    document: Document
    elements: list[tuple[int, Element]] = field(default_factory=list)
    headings: list[tuple[int, Heading]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    modal: tuple[int, Modal] | None = None
    text: str = ""
    _context: Callable[[int], Context] = field(default=lambda _index: ("", ""), repr=False)
    _covered: Callable[[int], bool] = field(default=lambda _index: False, repr=False)

    def section(self, index: int) -> str:
        """The landmark section that contains this node, such as an iframe owner."""
        return self._context(index)[0]

    def covered(self, index: int) -> bool:
        """Whether an overlay hides the visible part of this node, such as an iframe owner."""
        return self._covered(index)


def extract_frame(
    document: Document,
    *,
    frame_id: str,
    transform: FrameTransform,
    visible: Bounds | None,
    ref_prefix: str,
    focused: int | None,
    fallback_section: str,
    text_limit: int,
) -> FrameExtraction:
    return _FrameExtractor(
        document, frame_id, transform, visible, ref_prefix, focused, fallback_section
    ).run(text_limit)


class _FrameExtractor:
    def __init__(
        self,
        document: Document,
        frame_id: str,
        transform: FrameTransform,
        visible: Bounds | None,
        ref_prefix: str,
        focused: int | None,
        fallback_section: str,
    ) -> None:
        self._document = document
        self._frame_id = frame_id
        self._transform = transform
        self._visible = (
            visible if visible is not None and visible.width and visible.height else None
        )
        self._viewport = self._document_viewport()
        self._prefix = ref_prefix
        self._focused = focused
        self._fallback = fallback_section
        self._marked = document.with_any_attribute(_HINT_ATTRIBUTES)
        self._disabling = semantics.disabling_ancestors(document)
        self._contexts: dict[int, Context] = {}
        self._occlusion: Occlusion | None = None
        self._modal: int | None = None

    def run(self, text_limit: int) -> FrameExtraction:
        result = FrameExtraction(self._document, _context=self._context, _covered=self._covered)
        modal = self._find_modal()
        if modal is not None:
            self._modal = modal[1]
            result.modal = (modal[0], self._modal_view(modal[1]))
        result.elements = self._elements()
        result.headings, result.alerts = self._headings_and_alerts()
        if text_limit > 0:
            result.text = self._text(text_limit)
        return result

    # Elements

    def _elements(self) -> list[tuple[int, Element]]:
        document = self._document
        candidates: dict[int, bool] = {}
        placements: dict[int, tuple[Rect, Rect | None, bool]] = {}
        labels: list[int] = []
        for index in document.elements():
            if not document.is_element(index) or not document.has_layout(index):
                continue
            tag = document.tag(index)
            if tag == "label":
                labels.append(index)
                continue
            if tag in _SKIPPED_TAGS:
                continue
            semantic = self._candidate(index, tag)
            if semantic is None:
                continue
            placement = self._placement(index)
            if placement is not None:
                candidates[index] = semantic
                placements[index] = placement
        proxies = self._label_proxies(labels, candidates, placements)
        kept = self._deduplicate(candidates)
        built = [(index, self._element(index, placements[index], None)) for index in kept]
        built.extend(
            (index, self._element(index, placements[index], control)) for index, control in proxies
        )
        built.sort(key=lambda item: item[0])
        return built

    def _candidate(self, index: int, tag: str) -> bool | None:
        """True for semantic controls, False for generic clickable boxes, None otherwise."""
        document = self._document
        if tag in _NATIVE_TAGS:
            return self._native(index, tag)
        if tag == "option" and document.tag(document.parent(index)) in _OPTION_PARENTS:
            return None
        if index in self._marked:
            if semantics.role(document, index) in semantics.INTERACTIVE_ROLES:
                return True
            if self._hinted(index, tag):
                return False
        if index in document.clickable or self._pointer(index):
            return False
        return None

    def _native(self, index: int, tag: str) -> bool | None:
        attributes = self._document.attributes(index)
        if tag == "a" and "href" not in attributes:
            return False if index in self._document.clickable or index in self._marked else None
        if tag == "input" and attributes.get("type", "").lower() == "hidden":
            return None
        return True

    def _hinted(self, index: int, tag: str) -> bool:
        """Editors, delegated handlers, drag sources and focus stops without a control role."""
        attributes = self._document.attributes(index)
        return (
            semantics.editable(self._document, index)
            or any(name in attributes for name in _DELEGATED)
            or attributes.get("draggable") == "true"
            or (tag not in _CONTENT_TAGS and _focusable(attributes))
        )

    def _pointer(self, index: int) -> bool:
        document = self._document
        if document.style(index, Style.CURSOR) != "pointer":
            return False
        for parent in document.ancestors(index):
            if document.has_layout(parent):
                return document.style(parent, Style.CURSOR) != "pointer"
        return True

    def _placement(self, index: int) -> tuple[Rect, Rect | None, bool] | None:
        """Document rect, visible area and covered flag, or None when hidden."""
        document = self._document
        rect = document.rect(index)
        if rect is None or hidden(document, index, rect):
            return None
        area = visible_area(document, index, rect, self._viewport)
        return rect, area, area is not None and self._occluded(index, area)

    def _occluded(self, index: int, area: Rect) -> bool:
        if self._occlusion is None:
            self._occlusion = Occlusion(self._document, self._viewport)
        return self._occlusion.covered(index, area)

    def _covered(self, index: int) -> bool:
        placement = self._placement(index)
        return placement is not None and placement[2]

    def _label_proxies(
        self,
        labels: list[int],
        candidates: dict[int, bool],
        placements: dict[int, tuple[Rect, Rect | None, bool]],
    ) -> list[tuple[int, int]]:
        """Visible labels stand in for visually hidden checkboxes and radios."""
        document = self._document
        proxies = []
        for label in labels:
            control = document.linked_control(label)
            if control is None or control in candidates:
                continue
            if semantics.role(document, control) not in semantics.CHECKABLE_ROLES:
                continue
            placement = self._placement(label)
            if placement is not None:
                placements[label] = placement
                proxies.append((label, control))
        return proxies

    def _deduplicate(self, candidates: dict[int, bool]) -> list[int]:
        """Drop generic wrappers around real controls and generic boxes nested in controls."""
        document = self._document
        ordered = sorted(candidates)
        semantic = [index for index in ordered if candidates[index]]
        unwrapped = []
        for index in ordered:
            if not candidates[index]:
                position = bisect_right(semantic, index)
                if position < len(semantic) and semantic[position] < document.end(index):
                    continue
            unwrapped.append(index)
        kept: list[int] = []
        open_controls: list[int] = []
        for index in unwrapped:
            while open_controls and document.end(open_controls[-1]) <= index:
                open_controls.pop()
            if open_controls and not candidates[index]:
                continue
            kept.append(index)
            open_controls.append(index)
        return kept

    def _element(
        self, index: int, placement: tuple[Rect, Rect | None, bool], control: int | None
    ) -> Element:
        document = self._document
        source = index if control is None else control
        attributes = document.attributes(index)
        role = semantics.role(document, source)
        kind = semantics.input_type(document, source)
        rect, area, covered = placement
        section, group = self._context(index)
        href = attributes.get("href", "") if document.tag(index) in ("a", "area") else ""
        return Element.model_construct(
            ref=f"{self._prefix}{document.backend_ids[index]}",
            frame_id=self._frame_id,
            backend_id=document.backend_ids[index],
            role=role,
            name=document.text(index)
            if control is not None
            else semantics.name(document, index, role),
            tag=document.tag(index),
            input_type=kind,
            value=semantics.value(document, source, role, kind),
            placeholder=clean(
                attributes.get("placeholder") or attributes.get("aria-placeholder", ""), 80
            ),
            href=_absolute(document.url, href),
            options=semantics.options(document, source) if document.tag(source) == "select" else (),
            section=section,
            group=group,
            in_viewport=area is not None and not covered,
            covered=covered,
            pinned=document.pinned(index),
            bounds=self._bounds(rect, area),
            disabled=semantics.disabled(document, source, self._disabling),
            checked=semantics.checked(document, source, role),
            selected=semantics.selected(document, source),
            expanded=semantics.expanded(document, index),
            pressed=semantics.pressed(document, index),
            required=semantics.flag(document, source, "required", "aria-required"),
            readonly=semantics.flag(document, source, "readonly", "aria-readonly"),
            invalid=semantics.invalid(document, source),
            focused=self._focused is not None
            and self._focused
            in (
                document.backend_ids[index],
                document.backend_ids[source],
            ),
            has_popup=semantics.has_popup(document, index),
            current=semantics.current(document, index),
            draggable=attributes.get("draggable") == "true",
        )

    # Headings, alerts and dialogs

    def _headings_and_alerts(self) -> tuple[list[tuple[int, Heading]], list[str]]:
        document = self._document
        headings: list[tuple[int, Heading]] = []
        alerts: list[str] = []
        for index in document.elements():
            if not document.is_element(index) or not document.has_layout(index):
                continue
            tag = document.tag(index)
            is_heading = len(tag) == 2 and tag[0] == "h" and tag[1] in "123456"
            explicit = semantics.role(document, index) if index in self._marked else ""
            if not (is_heading or explicit in ("heading", *_ALERT_ROLES)):
                continue
            rect = document.rect(index)
            if rect is None or hidden(document, index, rect):
                continue
            if explicit in _ALERT_ROLES:
                text = document.text(index, 200)
                if text:
                    alerts.append(text)
                continue
            text = clean(document.attributes(index).get("aria-label", "")) or document.text(
                index, 120
            )
            if text:
                area = visible_area(document, index, rect, self._viewport)
                headings.append(
                    (
                        index,
                        Heading.model_construct(
                            level=semantics.heading_level(document, index),
                            text=text,
                            frame_id=self._frame_id,
                            in_viewport=area is not None and not self._occluded(index, area),
                            section=self._context(index)[0],
                        ),
                    )
                )
        return headings, list(dict.fromkeys(alerts))

    def _find_modal(self) -> tuple[int, int] | None:
        """The topmost visible modal dialog, as (paint order, index).

        Only native `<dialog open>` and `aria-modal="true"` count; whether a banner
        without them blocks the page shows up as covered elements instead.
        """
        document = self._document
        best: tuple[int, int] | None = None
        for index in document.elements():
            if not document.is_element(index) or not document.has_layout(index):
                continue
            if not self._modal_dialog(index):
                continue
            rect = document.rect(index)
            if rect is None or hidden(document, index, rect):
                continue
            if visible_area(document, index, rect, self._viewport) is None:
                continue
            candidate = (document.paint_order(index), index)
            if best is None or candidate > best:
                best = candidate
        return best

    def _modal_dialog(self, index: int) -> bool:
        document = self._document
        if document.tag(index) == "dialog":
            return document.has_attribute(index, "open")
        return (
            index in self._marked
            and document.attributes(index).get("aria-modal") == "true"
            and semantics.role(document, index) in ("dialog", "alertdialog")
        )

    def _modal_view(self, index: int) -> Modal:
        document = self._document
        role = semantics.role(document, index) or "dialog"
        return Modal(role=role, name=self._dialog_name(index))

    def _dialog_name(self, index: int) -> str:
        document = self._document
        name = semantics.labelled_by(document, index) or clean(
            document.attributes(index).get("aria-label", ""), 80
        )
        if name:
            return name
        for node in range(index + 1, document.end(index)):
            if document.is_element(node) and document.tag(node) in (
                "h1",
                "h2",
                "h3",
                "h4",
                "legend",
            ):
                return document.text(node, 80)
        return document.text(index, 60)

    # Context

    def _context(self, index: int) -> Context:
        """Section and group of a node, memoized along the ancestor path."""
        document = self._document
        contexts = self._contexts
        path = []
        node = document.parent(index)
        while node >= 0 and node not in contexts:
            path.append(node)
            node = document.parent(node)
        inherited = contexts[node] if node >= 0 else (self._fallback, "")
        for ancestor in reversed(path):
            inherited = self._contribution(ancestor, inherited)
            contexts[ancestor] = inherited
        return inherited

    def _contribution(self, node: int, inherited: Context) -> Context:
        document = self._document
        if not document.is_element(node):
            return inherited
        if node == self._modal:
            return (f"DIALOG: {self._dialog_name(node)}".rstrip(": "), "")
        role = semantics.role(document, node)
        landmark = _LANDMARKS.get(role)
        if landmark is not None:
            label = semantics.labelled_by(document, node) or clean(
                document.attributes(node).get("aria-label", ""), 60
            )
            if landmark == "DIALOG" and not label:
                label = self._dialog_name(node)
            return (f"{landmark}: {label}" if label else landmark, "")
        group = _GROUPS.get(role)
        if group is not None:
            label = (
                semantics.name(document, node, role)
                if role == "group"
                else (
                    semantics.labelled_by(document, node)
                    or clean(document.attributes(node).get("aria-label", ""), 60)
                )
            )
            if label:
                return (inherited[0], f'{group} "{label}"')
            if group in _UNNAMED_GROUPS:
                return (inherited[0], group)
        return inherited

    # Text and geometry

    def _text(self, limit: int) -> str:
        document = self._document
        parts: list[str] = []
        length = 0
        for node, value, rect in document.text_runs():
            if visible_area(document, document.parent(node), rect, self._viewport) is None:
                continue
            parts.append(value)
            length += len(value) + 1
            if length > limit:
                break
        # One extra character lets the caller detect truncation.
        return " ".join(parts)[: limit + 1]

    def _document_viewport(self) -> Rect | None:
        if self._visible is None:
            return None
        local = self._transform.bounds_to_local(self._visible)
        x, y = self._document.scroll
        return (local.x + x, local.y + y, local.x + local.width + x, local.y + local.height + y)

    def _bounds(self, rect: Rect, area: Rect | None) -> Bounds:
        x, y = self._document.scroll
        shown = area if area is not None else rect
        local = Bounds(
            x=shown[0] - x,
            y=shown[1] - y,
            width=max(0.0, shown[2] - shown[0]),
            height=max(0.0, shown[3] - shown[1]),
        )
        return self._transform.bounds_to_viewport(local)


def _absolute(base: str, href: str) -> str:
    if not href or href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def _focusable(attributes: dict[str, str]) -> bool:
    try:
        return int(attributes.get("tabindex", "-1")) >= 0
    except ValueError:
        return False
