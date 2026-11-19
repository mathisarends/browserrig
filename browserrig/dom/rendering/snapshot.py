"""Assemble a snapshot as compact, line-based text for a language model."""

from browserrig.dom.models import DomView
from browserrig.observation import Snapshot, header

from .sections import flow_body, render_body, render_canvases
from .text import cut


def render(snapshot: Snapshot) -> str:
    """List the viewport, nearby previews and explicit targets for inner scrolling."""
    page = DomView.of(snapshot)
    lines = header(snapshot)
    lines.extend(_page_state(page))
    if page.content is not None:
        lines.extend(flow_body(page))
    elif page.elements or page.headings or page.cookie_banners:
        lines.extend(render_body(page))
    if page.canvases:
        lines.extend(render_canvases(page.canvases))
    if snapshot.text and page.content is None:
        lines.extend(("", "page text:", snapshot.text))
    if snapshot.limitations:
        lines.append("")
        lines.extend(f"note: {limitation}" for limitation in snapshot.limitations)
    return "\n".join(lines)


def _page_state(page: DomView) -> list[str]:
    lines = []
    if page.modal is not None:
        name = f' "{cut(page.modal.name, 80)}"' if page.modal.name else ""
        guidance = (
            ""
            if any(banner.modal for banner in page.cookie_banners)
            else ("; interact with it first")
        )
        lines.append(f"modal: {page.modal.role}{name} is open{guidance}")
    if page.cookie_banners:
        lines.append(
            f"cookie banners: {len(page.cookie_banners)} detected heuristically"
        )
    if page.alerts:
        lines.append("alerts: " + " | ".join(cut(alert, 200) for alert in page.alerts))
    return lines
