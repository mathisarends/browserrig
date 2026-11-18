from collections import Counter

from browserrig.observation.flow import render_flow
from browserrig.observation.models import Canvas, ElementInfo, Heading, Snapshot

from .elements import render_element
from .text import cut, quote

_MAX_CANVASES = 10


def flow_body(snapshot: Snapshot) -> list[str]:
    def format_element(element: ElementInfo) -> str:
        return render_element(element, snapshot.url)

    body = render_flow(snapshot, None, format_element)
    lines = ["", "in viewport:", *(body or ["  (no visible content)"])]
    covered = [element for element in snapshot.elements if element.covered]
    if covered:
        lines.extend(("", f"covered by an overlay: {_summary(covered)}"))
    for position in ("above", "below"):
        preview = render_flow(snapshot, position, format_element)
        if preview:
            lines.extend(
                (
                    "",
                    f"{position} viewport (preview; refs scroll into view before acting):",
                )
            )
            lines.extend(preview)
    uploads: list[ElementInfo | Heading] = [
        element for element in snapshot.elements if _upload_outside_viewport(element)
    ]
    if uploads:
        lines.extend(("", "file inputs outside view (refs available):"))
        lines.extend(_blocks(uploads, snapshot.url))
    return lines


def render_body(snapshot: Snapshot) -> list[str]:
    """Only what the viewport shows; the header's scroll position tells what lies beyond."""
    items: list[ElementInfo | Heading] = [
        *(element for element in snapshot.elements if element.in_viewport),
        *(heading for heading in snapshot.headings if heading.in_viewport),
    ]
    lines = ["", "in viewport:"]
    banner_refs: set[str] = set()
    for banner in snapshot.cookie_banners:
        banner_refs.update(banner.refs)
    for banner in snapshot.cookie_banners:
        name = f": {cut(banner.name, 80)}" if banner.name else ""
        section = f"COOKIE BANNER{name}"
        lines.append(f"  [{section}]")
        if banner.text:
            lines.append(f"    text: {quote(banner.text, 600)}")
        controls: list[ElementInfo | Heading] = [
            element.model_copy(update={"section": section})
            for element in snapshot.elements
            if element.in_viewport and element.ref in banner.refs
        ]
        # The section header precedes the excerpt; reuse normal control/group rendering.
        lines.extend(_blocks(controls, snapshot.url)[1:])
    remaining = [
        item
        for item in items
        if not isinstance(item, ElementInfo) or item.ref not in banner_refs
    ]
    lines.extend(_blocks(remaining, snapshot.url))
    if not items and not snapshot.cookie_banners:
        lines.append("  (no interactive elements)")
    covered = [element for element in snapshot.elements if element.covered]
    if covered:
        lines.extend(("", f"covered by an overlay: {_summary(covered)}"))
    for position in ("above", "below"):
        preview: list[ElementInfo | Heading] = [
            item
            for item in (*snapshot.elements, *snapshot.headings)
            if _preview_item(item, position)
        ]
        if preview:
            lines.extend(
                (
                    "",
                    f"{position} viewport (preview; refs scroll into view before acting):",
                )
            )
            lines.extend(_blocks(preview, snapshot.url))
    uploads: list[ElementInfo | Heading] = [
        element for element in snapshot.elements if _upload_outside_viewport(element)
    ]
    if uploads:
        lines.extend(("", "file inputs outside view (refs available):"))
        lines.extend(_blocks(uploads, snapshot.url))
    return lines


def render_canvases(canvases: tuple[Canvas, ...]) -> list[str]:
    lines = [
        "",
        "canvases in viewport (viewport CSS pixels; no refs inside, use coordinates):",
    ]
    for canvas in canvases[:_MAX_CANVASES]:
        bounds = canvas.bounds
        parts = ["  canvas"]
        if canvas.name:
            parts.append(quote(canvas.name, 60))
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


def _preview_item(item: ElementInfo | Heading, position: str) -> bool:
    return (
        not item.in_viewport
        and item.outside_viewport == position
        and (not isinstance(item, ElementInfo) or not item.covered)
    )


def _upload_outside_viewport(element: ElementInfo) -> bool:
    return (
        element.input_type == "file"
        and not element.in_viewport
        and element.outside_viewport is None
    )


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
                    f"{indent}{'#' * min(item.level, 6)} {cut(item.text, 100)}"
                )
        else:
            heading = _titles(ordered[position - 1] if position else None, [item])
            prefix = f"{'#' * min(heading.level, 6)} " if heading else ""
            lines.append(indent + prefix + render_element(item, url))
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


def _summary(elements: list[ElementInfo]) -> str:
    counts = Counter(element.role or element.tag for element in elements)
    detail = ", ".join(f"{count} {role}" for role, count in counts.most_common(6))
    noun = "element" if len(elements) == 1 else "elements"
    return f"{len(elements)} {noun} ({detail})"
