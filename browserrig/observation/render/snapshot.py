"""Assemble a snapshot as compact, line-based text for a language model."""

from browserrig.observation.models import Snapshot

from .header import header
from .sections import flow_body, render_body, render_canvases


def render(snapshot: Snapshot) -> str:
    """List the viewport, nearby previews and explicit targets for inner scrolling."""
    lines = header(snapshot)
    if snapshot.content is not None:
        lines.extend(flow_body(snapshot))
    elif snapshot.elements or snapshot.headings or snapshot.cookie_banners:
        lines.extend(render_body(snapshot))
    if snapshot.canvases:
        lines.extend(render_canvases(snapshot.canvases))
    if snapshot.text and snapshot.content is None:
        lines.extend(("", "page text:", snapshot.text))
    if snapshot.limitations:
        lines.append("")
        lines.extend(f"note: {limitation}" for limitation in snapshot.limitations)
    return "\n".join(lines)
