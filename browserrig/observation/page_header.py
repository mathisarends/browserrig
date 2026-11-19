from browserrig.core import ReadinessStatus

from .models import Snapshot


def header(snapshot: Snapshot, *, metadata_only: bool = False) -> list[str]:
    """Describe the page, tab, viewport and cursor; page models append their content."""
    lines = [f"# {snapshot.title or '(untitled)'}", f"url: {snapshot.url}"]
    if len(snapshot.tabs) > 1 and not metadata_only:
        lines.append("tabs (* = this tab):")
        lines.extend(
            _tab(tab.id, tab.title or tab.url, tab.id == snapshot.tab_id)
            for tab in snapshot.tabs
        )
    else:
        lines.append(f"tab: {snapshot.tab_id}")
    if metadata_only and snapshot.tabs:
        lines.append(f"open tabs: {len(snapshot.tabs)}")
    if snapshot.width and snapshot.height:
        lines.append(_viewport(snapshot, metadata_only=metadata_only))
    lines.append(_cursor(snapshot))
    if snapshot.readiness != ReadinessStatus.READY:
        lines.append(f"readiness: {snapshot.readiness}")
        reason = snapshot.readiness_reason
        # Blocked and loading placeholders already say why in their text.
        if reason and (metadata_only or snapshot.parts or reason != snapshot.text):
            lines.append(reason)
    if snapshot.image and snapshot.geometry:
        lines.append(f"image: {_region(snapshot)}")
    return lines


def _tab(tab_id: str, title: str, current: bool) -> str:
    return f"  {'*' if current else ' '}{tab_id} {_cut(title, 60)}"


def _viewport(snapshot: Snapshot, *, metadata_only: bool) -> str:
    viewport = f"viewport: {snapshot.width:.0f}x{snapshot.height:.0f}"
    if snapshot.page_height <= 0:
        return viewport
    remaining = max(0.0, snapshot.page_height - snapshot.scroll_y - snapshot.height)
    if metadata_only:
        return (
            f"{viewport}, scroll y={snapshot.scroll_y:.0f}px, "
            f"{remaining:.0f}px remaining to page end"
        )
    if snapshot.page_height <= snapshot.height:
        return viewport
    above = snapshot.scroll_y / snapshot.height
    return (
        f"{viewport}, scroll {snapshot.scroll_y:.0f} of {snapshot.page_height:.0f}px"
        f" ({above:.1f} pages above, {remaining / snapshot.height:.1f} below)"
    )


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
        f"{geometry.width:.0f}x{geometry.height:.0f}{zoom}"
    )


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
