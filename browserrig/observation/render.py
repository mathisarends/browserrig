"""Render a snapshot as compact, line-based text for a language model.

One line per element keeps refs, roles and states scannable. Elements are grouped by
landmark section and form/menu group in document order, so structure costs a header
line instead of nesting on every element.
"""

import re
from collections import Counter
from urllib.parse import unquote, urlsplit

from browserrig.core import ReadinessStatus

from .models import CHECKABLE_ROLES, Canvas, ElementInfo, Heading, Snapshot
from .redirects import unwrap_redirect

_PLAIN_TYPES = frozenset(
    {"", "text", "checkbox", "radio", "submit", "button", "search"}
)
_FLAGS = ("required", "readonly", "invalid", "focused", "draggable")
_MAX_NAME = 100
_MAX_HREF = 80
_MAX_OPTIONS = 10
_MAX_CANVASES = 10
# Footnote markers such as [1], [a] or [note 3].
_FOOTNOTE = re.compile(r"\[\w[\w ]{0,7}\]")


def render(snapshot: Snapshot) -> str:
    """Lists only what the viewport shows; the agent scrolls to see the rest."""
    lines = _header(snapshot)
    if snapshot.elements or snapshot.headings:
        lines.extend(_body(snapshot))
    if snapshot.canvases:
        lines.extend(_canvases(snapshot.canvases))
    if snapshot.text:
        lines.extend(("", "page text:", snapshot.text))
    if snapshot.limitations:
        lines.append("")
        lines.extend(f"note: {limitation}" for limitation in snapshot.limitations)
    return "\n".join(lines)


def _header(snapshot: Snapshot) -> list[str]:
    lines = [f"# {snapshot.title or '(untitled)'}", f"url: {snapshot.url}"]
    if len(snapshot.tabs) > 1:
        lines.append("tabs (* = this tab):")
        lines.extend(
            _tab(tab.id, tab.title or tab.url, tab.id == snapshot.tab_id)
            for tab in snapshot.tabs
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
    lines.append(_cursor(snapshot))
    if snapshot.readiness != ReadinessStatus.READY:
        lines.append(f"readiness: {snapshot.readiness}")
        if snapshot.readiness_reason:
            lines.append(snapshot.readiness_reason)
    if snapshot.image and snapshot.geometry:
        lines.append(f"image: {_region(snapshot)}")
    if snapshot.modal is not None:
        name = f' "{_cut(snapshot.modal.name, 80)}"' if snapshot.modal.name else ""
        lines.append(
            f"modal: {snapshot.modal.role}{name} is open; interact with it first"
        )
    if snapshot.alerts:
        lines.append(
            "alerts: " + " | ".join(_cut(alert, 200) for alert in snapshot.alerts)
        )
    return lines


def _body(snapshot: Snapshot) -> list[str]:
    """Only what the viewport shows; the header's scroll position tells what lies beyond."""
    items: list[ElementInfo | Heading] = [
        *(element for element in snapshot.elements if element.in_viewport),
        *(heading for heading in snapshot.headings if heading.in_viewport),
    ]
    lines = ["", "in viewport:"]
    lines.extend(_blocks(items, snapshot.url) or ["  (no interactive elements)"])
    covered = [element for element in snapshot.elements if element.covered]
    if covered:
        lines.extend(("", f"covered by an overlay: {_summary(covered)}"))
    return lines


def _cursor(snapshot: Snapshot) -> str:
    """The pointer position matters for hover, scroll and coordinate tools without an image."""
    cursor = snapshot.cursor
    if cursor is None:
        return "cursor: not in this tab yet"
    return f"cursor: x={cursor.x:.0f} y={cursor.y:.0f} (viewport CSS pixels)"


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
    lines = [
        "",
        "canvases in viewport (viewport CSS pixels; no refs inside, use coordinates):",
    ]
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


def _blocks(items: list[ElementInfo | Heading], url: str) -> list[str]:
    """Lines for items in document order, with section and group header lines."""
    lines: list[str] = []
    section: str | None = None
    group = ""
    ordered = sorted(items, key=lambda entry: entry.order)
    for position, item in enumerate(ordered):
        if item.section != section:
            section, group = item.section, ""
            if item.section:
                lines.append(f"  [{item.section}]")
        current = item.group if isinstance(item, ElementInfo) else group
        if current != group:
            group = current
            if group:
                lines.append(f"    <{group}>")
        indent = "  " * (1 + bool(section) + bool(group))
        if isinstance(item, Heading):
            # A heading that is just a link, as on search result pages, is the link's line.
            if not _titles(item, ordered[position + 1 : position + 2]):
                lines.append(
                    f"{indent}{'#' * min(item.level, 6)} {_cut(item.text, 100)}"
                )
        else:
            heading = _titles(ordered[position - 1] if position else None, [item])
            prefix = f"{'#' * min(heading.level, 6)} " if heading else ""
            lines.append(indent + prefix + _element(item, url))
    return lines


def _titles(
    heading: ElementInfo | Heading | None, following: list[ElementInfo | Heading]
) -> Heading | None:
    """`heading` when the next item is an element named exactly like it."""
    if not isinstance(heading, Heading) or not following:
        return None
    element = following[0]
    return (
        heading
        if isinstance(element, ElementInfo) and element.name == heading.text
        else None
    )


def _element(element: ElementInfo, url: str) -> str:
    role = element.role if element.role and element.role != "generic" else element.tag
    parts = [f"{'*' if element.new else ''}[{element.ref}] {role}"]
    if element.input_type not in _PLAIN_TYPES:
        parts[0] += f"[type={element.input_type}]"
    if element.name:
        parts.append(_quote(element.name, _MAX_NAME))
    parts.extend(_states(element))
    if element.value is not None and element.value != element.name:
        parts.append(f"value={_quote(element.value, 100)}")
    if (
        element.placeholder
        and element.placeholder != element.name
        and not element.value
    ):
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
    link = _link(element.href, url, element.name)
    if link:
        parts.append(f"-> {link}")
    elif not element.name and element.bounds is not None and element.value is None:
        # Without a name, size and place are what tell icons, tiles and wrappers apart.
        bounds = element.bounds
        parts.append(
            f"x={bounds.x:.0f} y={bounds.y:.0f} {bounds.width:.0f}x{bounds.height:.0f}"
        )
    return " ".join(parts)


def _states(element: ElementInfo) -> list[str]:
    unchecked = "unchecked" if element.role in CHECKABLE_ROLES else ""
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


def _link(href: str, url: str, name: str = "") -> str:
    """Same-page links as fragments, same-origin links as paths; script links are omitted."""
    href = unwrap_redirect(href)
    parts = urlsplit(href)
    if parts.scheme not in ("http", "https", "mailto", "tel"):
        return ""
    page = url.split("#", 1)[0]
    if href.startswith(page + "#"):
        fragment = href[len(page) + 1 :]
        # Table-of-contents entries and footnote markers say nothing more with their target.
        if (
            not fragment
            or unquote(fragment).replace("_", " ").casefold() == name.casefold()
            or _FOOTNOTE.fullmatch(name)
        ):
            return ""
        return _cut("#" + fragment, _MAX_HREF)
    origin = _origin(url)
    if origin and href.startswith(origin + "/"):
        href = href[len(origin) :]
    return _cut(href, _MAX_HREF)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return (
        f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") else ""
    )


def _summary(elements: list[ElementInfo]) -> str:
    counts = Counter(element.role or element.tag for element in elements)
    detail = ", ".join(f"{count} {role}" for role, count in counts.most_common(6))
    noun = "element" if len(elements) == 1 else "elements"
    return f"{len(elements)} {noun} ({detail})"


def _tab(tab_id: str, title: str, current: bool) -> str:
    return f"  {'*' if current else ' '}{tab_id} {_cut(title, 60)}"


def _quote(text: str, limit: int) -> str:
    return '"' + _cut(text, limit).replace('"', "'") + '"'


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
