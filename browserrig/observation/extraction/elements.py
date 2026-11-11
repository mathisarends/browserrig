"""Turn one indexed frame document into elements, headings, alerts and page text."""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urljoin

from browserrig.core import Bounds, FrameTransform
from browserrig.observation.models import (
    CHECKABLE_ROLES,
    Canvas,
    CookieBanner,
    Element,
    Heading,
    Modal,
    Offscreen,
    ScrollInfo,
    TextBlock,
)

from . import semantics
from .cookies import cookie_banners
from .document import Document, Rect, clean
from .flow import TextCollector
from .styles import Style
from .visibility import Occlusion, hidden, visible_area

_SKIPPED_TAGS = frozenset(
    {
        "html",
        "body",
        "head",
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "frame",
        "label",
    }
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
# Smaller canvases are icons, sparklines or tracking pixels, not drawing surfaces.
_MIN_CANVAS_SIDE = 24

type Context = tuple[str, str]
"""Section and group labels that apply to a node's descendants."""


@dataclass(slots=True)
class FrameExtraction:
    """Results keyed by document order so frames can be merged into page order."""

    document: Document
    elements: list[tuple[int, Element]] = field(default_factory=list)
    headings: list[tuple[int, Heading]] = field(default_factory=list)
    canvases: list[tuple[int, Canvas]] = field(default_factory=list)
    offscreen: list[Offscreen] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    modal: tuple[int, Modal] | None = None
    cookie_banners: tuple[CookieBanner, ...] = ()
    text: str = ""
    texts: list[tuple[int, TextBlock]] = field(default_factory=list)
    _context: Callable[[int], Context] = field(
        default=lambda _index: ("", ""), repr=False
    )
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
    embedded: bool = False,
    viewport_expansion: int = 1000,
) -> FrameExtraction:
    extractor = _FrameExtractor(
        document,
        frame_id=frame_id,
        transform=transform,
        visible=visible,
        ref_prefix=ref_prefix,
        focused=focused,
        fallback_section=fallback_section,
        viewport_expansion=viewport_expansion,
    )
    return extractor.run(text_limit, embedded=embedded)


class _FrameExtractor:
    def __init__(
        self,
        document: Document,
        *,
        frame_id: str,
        transform: FrameTransform,
        visible: Bounds | None,
        ref_prefix: str,
        focused: int | None,
        fallback_section: str,
        viewport_expansion: int,
    ) -> None:
        self._document = document
        self._frame_id = frame_id
        self._transform = transform
        self._visible = (
            visible
            if visible is not None and visible.width and visible.height
            else None
        )
        self._viewport = self._document_viewport()
        self._preview = (
            (
                self._viewport[0],
                max(0, self._viewport[1] - viewport_expansion),
                self._viewport[2],
                min(
                    self._viewport[3] + viewport_expansion,
                    document.content_height or self._viewport[3] + viewport_expansion,
                ),
            )
            if self._viewport is not None
            else None
        )
        self._scrolls: dict[int, ScrollInfo] = {}
        self._prefix = ref_prefix
        self._focused = focused
        self._fallback = fallback_section
        self._marked = document.with_any_attribute(_HINT_ATTRIBUTES)
        self._disabling = semantics.disabling_ancestors(document)
        self._contexts: dict[int, Context] = {}
        self._occlusion: Occlusion | None = None
        self._modal: int | None = None

    def run(self, text_limit: int, *, embedded: bool = False) -> FrameExtraction:
        result = FrameExtraction(
            self._document, _context=self._context, _covered=self._covered
        )
        modal = self._find_modal()
        if modal is not None:
            self._modal = modal[1]
            result.modal = (modal[0], self._modal_view(modal[1]))
        result.elements, result.offscreen = self._elements()
        result.cookie_banners = cookie_banners(
            self._document,
            result.elements,
            viewport=self._viewport,
            covered=self._occluded,
            modal=self._modal,
            embedded=embedded,
        )
        result.headings, result.alerts = self._headings_and_alerts()
        result.canvases = self._canvases({index for index, _ in result.elements})
        if text_limit > 0:
            result.text, result.texts = self._text(text_limit, result)
        return result

    # Elements

    def _elements(self) -> tuple[list[tuple[int, Element]], list[Offscreen]]:
        """Controls the viewport shows, and the identities of the rest.

        Names, values and states are derived only for shown controls; that work dominates
        extraction on long pages.
        """
        document = self._document
        candidates: dict[int, bool] = {}
        placements: dict[int, tuple[Rect, Rect | None, bool]] = {}
        labels: list[int] = []
        hidden_uploads: list[int] = []
        for index in document.elements():
            if not document.is_element(index):
                continue
            tag = document.tag(index)
            if (
                tag == "input"
                and semantics.input_type(document, index) == "file"
                and self._placement(index) is None
            ):
                hidden_uploads.append(index)
                continue
            if not document.has_layout(index):
                continue
            if tag == "label":
                labels.append(index)
                continue
            if tag in _SKIPPED_TAGS:
                continue
            scroll = document.scroll_info(index)
            if scroll is not None:
                self._scrolls[index] = scroll
            semantic = self._candidate(index, tag)
            if semantic is None:
                continue
            placement = self._placement(index)
            if placement is not None:
                candidates[index] = semantic
                placements[index] = placement
        proxies = self._label_proxies(labels, candidates, placements)
        kept: list[tuple[int, int | None]] = [
            (index, None) for index in self._deduplicate(candidates)
        ]
        kept.extend(proxies)
        built: list[tuple[int, Element]] = []
        offscreen: list[Offscreen] = []
        upload_labels: dict[int, str] = {}
        for index, control in kept:
            rect = placements[index][0]
            if (
                placements[index][1] is not None
                or visible_area(document, index, rect, self._preview) is not None
            ):
                element = self._element(index, placements[index], control)
                built.append((index, element))
                if (
                    control is not None
                    and element.input_type == "file"
                    and not element.covered
                    and (control not in upload_labels or element.in_viewport)
                ):
                    upload_labels[control] = element.ref
                continue
            backend_id = document.backend_ids[index]
            offscreen.append(
                Offscreen.model_construct(
                    ref=f"{self._prefix}{backend_id}",
                    frame_id=self._frame_id,
                    backend_id=backend_id,
                )
            )
        built.extend(
            (
                index,
                self._element(index, ((0, 0, 0, 0), None, False), None).model_copy(
                    update={
                        "bounds": None,
                        "outside_viewport": None,
                        "upload_label_ref": upload_labels.get(index),
                    }
                ),
            )
            for index in hidden_uploads
        )
        built.sort(key=lambda item: item[0])
        return built, offscreen

    def _candidate(self, index: int, tag: str) -> bool | None:
        """True for semantic controls, False for generic clickable boxes, None otherwise."""
        document = self._document
        listed_option = (
            tag == "option" and document.tag(document.parent(index)) in _OPTION_PARENTS
        )
        if listed_option or self._decorative(index):
            return None
        if index in self._scrolls or tag in _NATIVE_TAGS:
            return True if index in self._scrolls else self._native(index, tag)
        if index in self._marked:
            if semantics.role(document, index) in semantics.INTERACTIVE_ROLES:
                return True
            if self._hinted(index, tag):
                return False
        if index in document.clickable or self._pointer(index):
            return False
        return None

    def _decorative(self, index: int) -> bool:
        """Hidden from assistive technology and taken out of the focus order on purpose.

        Sites do this to duplicates such as an image link beside its title link or a styled
        box over a native select; Chrome's accessibility tree omits them too.
        """
        document = self._document
        if document.attributes(index).get("tabindex", "").strip() != "-1":
            return False
        return any(
            document.attributes(node).get("aria-hidden", "").strip().lower() == "true"
            for node in (index, *document.ancestors(index))
        )

    def _native(self, index: int, tag: str) -> bool | None:
        attributes = self._document.attributes(index)
        if tag == "a" and "href" not in attributes:
            return (
                False
                if index in self._document.clickable or index in self._marked
                else None
            )
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

    def _covered(self, index: int) -> bool:
        placement = self._placement(index)
        return placement is not None and placement[2]

    def _label_proxies(
        self,
        labels: list[int],
        candidates: dict[int, bool],
        placements: dict[int, tuple[Rect, Rect | None, bool]],
    ) -> list[tuple[int, int]]:
        """Visible labels stand in for hidden checkable controls and file inputs."""
        document = self._document
        proxies = []
        for label in labels:
            control = document.linked_control(label)
            if control is None or control in candidates:
                continue
            if (
                semantics.role(document, control) not in CHECKABLE_ROLES
                and semantics.input_type(document, control) != "file"
            ):
                continue
            placement = self._placement(label)
            if placement is not None:
                placements[label] = placement
                proxies.append((label, control))
        return proxies

    def _canvases(self, listed: set[int]) -> list[tuple[int, Canvas]]:
        """Visible, uncovered canvases; `listed` holds indexes already built as elements."""
        document = self._document
        canvases: list[tuple[int, Canvas]] = []
        for index in document.elements():
            if not document.is_element(index) or document.tag(index) != "canvas":
                continue
            if not document.has_layout(index):
                continue
            placement = self._placement(index)
            if placement is None:
                continue
            rect, area, covered = placement
            if area is None or covered:
                continue
            bounds = self._bounds(rect, area)
            if min(bounds.width, bounds.height) < _MIN_CANVAS_SIDE:
                continue
            attributes = document.attributes(index)
            canvases.append(
                (
                    index,
                    Canvas.model_construct(
                        frame_id=self._frame_id,
                        bounds=bounds,
                        name=semantics.labelled_by(document, index)
                        or clean(
                            attributes.get("aria-label") or attributes.get("title", ""),
                            80,
                        ),
                        ref=f"{self._prefix}{document.backend_ids[index]}"
                        if index in listed
                        else "",
                        clipped=area != rect,
                    ),
                )
            )
        return canvases

    def _placement(self, index: int) -> tuple[Rect, Rect | None, bool] | None:
        """Document rect, visible area and covered flag, or None when hidden."""
        document = self._document
        rect = document.rect(index)
        if rect is None or hidden(document, index, rect):
            return None
        area = visible_area(document, index, rect, self._viewport)
        return rect, area, area is not None and self._occluded(index, area)

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
            text = clean(
                document.attributes(index).get("aria-label", "")
            ) or document.text(index, 120)
            area = visible_area(document, index, rect, self._viewport)
            preview = visible_area(document, index, rect, self._preview)
            if (
                text
                and preview is not None
                and not (area is not None and self._occluded(index, area))
            ):
                headings.append(
                    (
                        index,
                        Heading.model_construct(
                            level=semantics.heading_level(document, index),
                            text=text,
                            frame_id=self._frame_id,
                            section=self._context(index)[0],
                            in_viewport=area is not None,
                            outside_viewport=self._outside(rect)
                            if area is None
                            else None,
                        ),
                    )
                )
        return headings, list(dict.fromkeys(alerts))

    def _text(
        self, limit: int, result: FrameExtraction
    ) -> tuple[str, list[tuple[int, TextBlock]]]:
        document = self._document
        collector = TextCollector(document, result.elements, result.headings, limit)
        parts: dict[str, list[str]] = {"visible": [], "above": [], "below": []}
        lengths = dict.fromkeys(parts, 0)
        for node, raw, rect in document.text_runs(raw=True):
            value = clean(raw, 1000)
            parent = document.parent(node)
            if hidden(document, parent, rect):
                continue
            area = visible_area(document, parent, rect, self._viewport)
            # Text under an overlay is not what the page shows.
            preview = visible_area(document, parent, rect, self._preview)
            if preview is None or area is not None and self._occluded(parent, area):
                continue
            position = "visible" if area is not None else self._outside(rect)
            if position is None:
                continue
            collector.add(
                node,
                raw,
                TextBlock(
                    text="",
                    frame_id=self._frame_id,
                    bounds=self._bounds(rect, area),
                    in_viewport=area is not None,
                    outside_viewport=self._outside(rect) if area is None else None,
                ),
            )
            if lengths[position] <= limit:
                parts[position].append(value)
                lengths[position] += len(value) + 1
        text = " ".join(parts["visible"])
        for position in ("above", "below"):
            if parts[position]:
                text += f"\n[{position} viewport] " + " ".join(parts[position])
        # One extra character lets the caller detect truncation.
        return text.strip()[: limit + 1], collector.finish()

    def _occluded(self, index: int, area: Rect) -> bool:
        if self._occlusion is None:
            self._occlusion = Occlusion(self._document, self._viewport)
        return self._occlusion.covered(index, area)

    def _deduplicate(self, candidates: dict[int, bool]) -> list[int]:
        """Drop generic wrappers around real controls and generic boxes nested in controls."""
        document = self._document
        ordered = sorted(candidates)
        semantic = [index for index in ordered if candidates[index]]
        unwrapped = []
        for index in ordered:
            if not candidates[index]:
                position = bisect_right(semantic, index)
                if position < len(semantic) and semantic[position] < document.end(
                    index
                ):
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
            if index not in self._scrolls:
                open_controls.append(index)
        return kept

    def _element(
        self, index: int, placement: tuple[Rect, Rect | None, bool], control: int | None
    ) -> Element:
        document = self._document
        source = index if control is None else control
        attributes = document.attributes(index)
        role = semantics.role(document, source)
        scroll = self._scrolls.get(index)
        if scroll is not None and role in {"", "generic"}:
            role = "region"
        kind = semantics.input_type(document, source)
        rect, area, covered = placement
        section, group = self._context(index)
        href = (
            attributes.get("href", "") if document.tag(index) in ("a", "area") else ""
        )
        return Element.model_construct(
            ref=f"{self._prefix}{document.backend_ids[index]}",
            frame_id=self._frame_id,
            backend_id=document.backend_ids[index],
            role=role,
            # A label standing in for its control is named like the control.
            name=semantics.name(document, control, role) or document.text(index)
            if control is not None
            else semantics.name(document, index, role),
            tag=document.tag(index),
            input_type=kind,
            description=semantics.description(document, source),
            scroll=scroll,
            value=semantics.value(document, source, role, kind),
            placeholder=clean(
                attributes.get("placeholder") or attributes.get("aria-placeholder", ""),
                80,
            ),
            href=_absolute(document.url, href),
            options=semantics.options(document, source)
            if document.tag(source) == "select"
            else (),
            multiple=(
                document.tag(source) == "select"
                and "multiple" in document.attributes(source)
            )
            or document.attributes(source).get("aria-multiselectable") == "true",
            control_id=clean(document.attributes(source).get("id", ""), 100)
            if kind in {"radio", "checkbox"}
            else "",
            selection_group=clean(document.attributes(source).get("name", ""), 100)
            if kind == "radio"
            else "",
            section=section,
            group=group,
            in_viewport=area is not None and not covered,
            outside_viewport=self._outside(rect) if area is None else None,
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

    # Canvases

    # Headings, alerts and dialogs

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

    # Text and geometry

    def _document_viewport(self) -> Rect | None:
        if self._visible is None:
            return None
        local = self._transform.bounds_to_local(self._visible)
        x, y = self._document.scroll
        return (
            local.x + x,
            local.y + y,
            local.x + local.width + x,
            local.y + local.height + y,
        )

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

    def _outside(self, rect: Rect) -> Literal["above", "below"] | None:
        if self._viewport is None:
            return None
        if rect[3] <= self._viewport[1]:
            return "above"
        if rect[1] >= self._viewport[3]:
            return "below"
        return None


def _absolute(base: str, href: str) -> str:
    if not href or href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def _focusable(attributes: dict[str, str]) -> bool:
    try:
        return int(attributes.get("tabindex", "-1")) >= 0
    except ValueError:
        return False
