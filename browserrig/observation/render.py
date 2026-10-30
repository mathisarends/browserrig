"""Render a snapshot as compact, line-based text for a language model.

One line per element keeps refs, roles and states scannable. Elements are grouped by
landmark section and form/menu group in document order, so structure costs a header
line instead of nesting on every element.
"""

from collections import Counter
from urllib.parse import urlsplit

from browserrig.core.kinds import ObservationKind, ReadinessStatus

from .models import Canvas, Element, Heading, Snapshot

_CHECKABLE = frozenset({"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"})
_PLAIN_TYPES = frozenset({"", "text", "checkbox", "radio", "submit", "button", "search"})
_FLAGS = ("required", "readonly", "invalid", "focused", "draggable")
_MAX_NAME = 100
_MAX_HREF = 80
_MAX_OPTIONS = 10
_MAX_HEADINGS = 30
_MAX_CANVASES = 10


def render(snapshot: Snapshot, *, offscreen: int = 40) -> str:
    """`offscreen` caps how many elements outside the viewport are listed individually."""
    lines = _header(snapshot)
    if snapshot.mode == ObservationKind.CANVAS:
        lines.append("Canvas observation: no element refs; point with image coordinates.")
    else:
        if snapshot.elements or snapshot.headings:
            lines.extend(_body(snapshot, offscreen))
        if snapshot.canvases:
            lines.extend(_canvases(snapshot.canvases))
    if snapshot.text:
        lines.extend(("", "page text:", snapshot.text))
    if snapshot.limitations:
        lines.append("")
        lines.extend(f"note: {limitation}" for limitation in snapshot.limitations)
    return "\n".join(lines)


def image_caption(snapshot: Snapshot) -> str:
    """Text placed before an observation image, naming the area it shows."""
    caption = f"Current {snapshot.mode} observation {snapshot.id}"
    if snapshot.mode == ObservationKind.DOM and snapshot.geometry:
        caption += f"; {_region(snapshot)}"
    return caption


def _header(snapshot: Snapshot) -> list[str]:
    lines = [f"# {snapshot.title or '(untitled)'}", f"url: {snapshot.url}"]
    if len(snapshot.tabs) > 1:
        lines.append("tabs (* = this tab):")
        lines.extend(
            _tab(tab.id, tab.title or tab.url, tab.id == snapshot.tab_id) for tab in snapshot.tabs
        )
    else:
        lines.append(f"tab: {snapshot.tab_id}")
    if snapshot.width and snapshot.height:
        viewport = f"viewport: {snapshot.width:.0f}x{snapshot.height:.0f}"
        if snapshot.page_height > snapshot.height:
            above = snapshot.scroll_y / snapshot.height
            below = max(0.0, snapshot.page_height - snapshot.scroll_y - snapshot.height)
            viewport += (
                f", scroll {snapshot.scroll_y:.0f} of {snapshot.page_height:.0f}px"
                f" ({above:.1f} pages above, {below / snapshot.height:.1f} below)"
            )
        lines.append(viewport)
    if snapshot.readiness != ReadinessStatus.READY:
        lines.append(f"readiness: {snapshot.readiness}")
    if snapshot.mode == ObservationKind.DOM and snapshot.image and snapshot.geometry:
        lines.append(f"image: {_region(snapshot)}")
    if snapshot.modal is not None:
        name = f' "{_cut(snapshot.modal.name, 80)}"' if snapshot.modal.name else ""
        lines.append(f"modal: {snapshot.modal.role}{name} is open; interact with it first")
    if snapshot.alerts:
        lines.append("alerts: " + " | ".join(_cut(alert, 200) for alert in snapshot.alerts))
    return lines


def _body(snapshot: Snapshot, offscreen: int) -> list[str]:
    visible = [element for element in snapshot.elements if element.in_viewport]
    covered = [element for element in snapshot.elements if element.covered]
    hidden = [
        element for element in snapshot.elements if not element.in_viewport and not element.covered
    ]
    above = [element for element in hidden if _side(element, snapshot.height) < 0]
    below = [element for element in hidden if _side(element, snapshot.height) > 0]
    aside = [element for element in hidden if _side(element, snapshot.height) == 0]
    listed = set(map(id, _nearest(hidden, snapshot.height, offscreen)))
    url = snapshot.url
    shown = [item.order for item in (*visible, *snapshot.headings) if item.in_viewport]
    first, last = (min(shown), max(shown)) if shown else (-1, -1)

    lines = ["", "in viewport:"]
    items: list[Element | Heading] = [*visible, *(h for h in snapshot.headings if h.in_viewport)]
    lines.extend(_blocks(items, url) or ["  (no interactive elements)"])
    for label, group in (("above viewport", above), ("below viewport", below)):
        if not group:
            continue
        lines.extend(("", f"{label}: {_summary(group)}"))
        headings = [
            heading
            for heading in snapshot.headings
            if not heading.in_viewport
            and (heading.order > last if label.startswith("below") else heading.order < first)
        ]
        if headings:
            shown = " · ".join(_cut(heading.text, 60) for heading in headings[:_MAX_HEADINGS])
            more = f" · …+{len(headings) - _MAX_HEADINGS}" if len(headings) > _MAX_HEADINGS else ""
            lines.append(f"  headings: {shown}{more}")
        lines.extend(_blocks([element for element in group if id(element) in listed], url))
    if aside:
        lines.extend(("", f"inside scrollable areas or beside the viewport: {_summary(aside)}"))
        lines.extend(_blocks([element for element in aside if id(element) in listed], url))
    if covered:
        lines.extend(("", f"covered by an overlay: {_summary(covered)}"))
    return lines


def _region(snapshot: Snapshot) -> str:
    geometry = snapshot.geometry
    assert geometry is not None
    zoom = f" at {geometry.scale:g}x zoom" if geometry.scale != 1 else ""
    return (
        f"viewport region x={geometry.x:.0f} y={geometry.y:.0f} "
        f"{geometry.width:.0f}x{geometry.height:.0f}{zoom}; move_mouse, click_at and drag_at take "
        "pixels of this image until the next observation"
    )


def _canvases(canvases: tuple[Canvas, ...]) -> list[str]:
    lines = ["", "canvases in viewport (viewport CSS pixels; no refs inside, use coordinates):"]
    for canvas in canvases[:_MAX_CANVASES]:
        bounds = canvas.bounds
        parts = ["  canvas"]
        if canvas.name:
            parts.append(_quote(canvas.name, 60))
        if canvas.ref:
            parts.append(f"(ref {canvas.ref})")
        parts.append(
            f"x={bounds.x:.0f} y={bounds.y:.0f} {bounds.width:.0f}x{bounds.height:.0f} "
            f"center={bounds.x + bounds.width / 2:.0f},{bounds.y + bounds.height / 2:.0f}"
        )
        if canvas.clipped:
            parts.append("(visible part)")
        lines.append(" ".join(parts))
    if len(canvases) > _MAX_CANVASES:
        lines.append(f"  …+{len(canvases) - _MAX_CANVASES} more canvases")
    return lines


def _blocks(items: list[Element | Heading], url: str) -> list[str]:
    """Lines for items in document order, with section and group header lines."""
    lines: list[str] = []
    section: str | None = None
    group = ""
    for item in sorted(items, key=lambda entry: entry.order):
        if item.section != section:
            section, group = item.section, ""
            if item.section:
                lines.append(f"  [{item.section}]")
        current = item.group if isinstance(item, Element) else group
        if current != group:
            group = current
            if group:
                lines.append(f"    <{group}>")
        indent = "  " * (1 + bool(section) + bool(group))
        if isinstance(item, Heading):
            lines.append(f"{indent}{'#' * min(item.level, 6)} {_cut(item.text, 100)}")
        else:
            lines.append(indent + _element(item, url))
    return lines


def _element(element: Element, url: str) -> str:
    role = element.role if element.role and element.role != "generic" else element.tag
    parts = [f"{'*' if element.new else ''}[{element.ref}] {role}"]
    if element.input_type not in _PLAIN_TYPES:
        parts[0] += f"[type={element.input_type}]"
    if element.name:
        parts.append(_quote(element.name, _MAX_NAME))
    parts.extend(_states(element))
    if element.value is not None and element.value != element.name:
        parts.append(f"value={_quote(element.value, 100)}")
    if element.placeholder and element.placeholder != element.name and not element.value:
        parts.append(f"placeholder={_quote(element.placeholder, 60)}")
    if element.options:
        shown = [
            f"{_cut(option.label, 40)}{'*' if option.selected else ''}"
            f"{' (disabled)' if option.disabled else ''}"
            for option in element.options[:_MAX_OPTIONS]
        ]
        if len(element.options) > _MAX_OPTIONS:
            shown.append(f"…+{len(element.options) - _MAX_OPTIONS}")
        parts.append(f"options=[{', '.join(shown)}]")
    link = _link(element.href, url)
    if link:
        parts.append(f"-> {link}")
    return " ".join(parts)


def _states(element: Element) -> list[str]:
    unchecked = "unchecked" if element.role in _CHECKABLE else ""
    current = element.current
    states = [
        "disabled" if element.disabled else "",
        _tristate(element.checked, "checked", unchecked, "mixed"),
        "selected" if element.selected else "",
        _tristate(element.pressed, "pressed", "", "pressed=mixed"),
        _tristate(element.expanded, "expanded", "collapsed", ""),
        f"haspopup={element.has_popup}" if element.has_popup else "",
        ("current" if current == "true" else f"current={current}") if current else "",
        *(flag for flag in _FLAGS if getattr(element, flag)),
    ]
    return [state for state in states if state]


def _tristate(value: object, on: str, off: str, mixed: str) -> str:
    if value == "mixed":
        return mixed
    if value is True:
        return on
    return off if value is False else ""


def _link(href: str, url: str) -> str:
    """Same-page links as fragments, same-origin links as paths; script links are omitted."""
    parts = urlsplit(href)
    if parts.scheme not in ("http", "https", "mailto", "tel"):
        return ""
    page = url.split("#", 1)[0]
    if href.startswith(page + "#"):
        return _cut(href[len(page) :], _MAX_HREF) if len(href) > len(page) + 1 else ""
    origin = _origin(url)
    if origin and href.startswith(origin + "/"):
        href = href[len(origin) :]
    return _cut(href, _MAX_HREF)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") else ""


def _summary(elements: list[Element]) -> str:
    counts = Counter(element.role or element.tag for element in elements)
    detail = ", ".join(f"{count} {role}" for role, count in counts.most_common(6))
    noun = "element" if len(elements) == 1 else "elements"
    return f"{len(elements)} {noun} ({detail})"


def _nearest(elements: list[Element], height: float, limit: int) -> list[Element]:
    def distance(element: Element) -> float:
        if element.bounds is None:
            return float("inf")
        if element.bounds.y >= height:
            return element.bounds.y - height
        bottom = element.bounds.y + element.bounds.height
        return -bottom if bottom <= 0 else abs(element.bounds.x)

    return sorted(elements, key=distance)[: max(0, limit)]


def _side(element: Element, height: float) -> int:
    """-1 above the viewport, 1 below it, 0 beside it or inside a scroll container."""
    if element.bounds is None:
        return 0
    if element.bounds.y >= height:
        return 1
    if element.bounds.y + element.bounds.height <= 0:
        return -1
    return 0


def _tab(tab_id: str, title: str, current: bool) -> str:
    return f"  {'*' if current else ' '}{tab_id} {_cut(title, 60)}"


def _quote(text: str, limit: int) -> str:
    return '"' + _cut(text, limit).replace('"', "'") + '"'


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
