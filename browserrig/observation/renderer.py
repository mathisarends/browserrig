from typing import Protocol

from .config import Screenshots, ScreenshotTrigger
from .models import Snapshot
from .render import render, render_metadata


class Renderer(Protocol):
    def instructions(self) -> str:
        """Explain how to read the text projection."""

    def refs(self) -> str | None:
        """Describe how to use target refs, or None when refs are unavailable."""

    def render(self, snapshot: Snapshot) -> str:
        """Format a snapshot as the observation text supplied to the agent."""


class DomRenderer:
    """Format the DOM content present in the snapshot."""

    def instructions(self) -> str:
        return (
            "Each observation starts with a page header, then lists interactive elements "
            'one per line as `[ref] role "name" states value=... -> link`. Landmarks such as '
            '[MAIN] and groups like <form "Login"> may organize the controls. '
            "A leading * marks elements new since the previous observation. "
            "Inside iframes, above/below previews refer to the frame's viewport. "
            "An element with scroll(up=..., down=...) is an inner scroll container. "
            "Use scroll_element(ref=...) for that panel and scroll_page for the page. "
            "Multiple marks multi-select controls. Options show * for selected entries "
            "and explicit values when available. Radio IDs, values and selection_group "
            "are raw page metadata. Modal dialogs can block controls outside them. "
            "Cookie banner detection is heuristic. Choose whether to interact or navigate. "
            "Canvas content has no DOM refs. "
            "When visible prose is included, it appears in reading order beside its controls. "
            "Plain text has no action refs. Links in prose use [label][ref]. Use search_page "
            "to find text beyond the included prose."
        )

    def refs(self) -> str:
        return (
            "Pass the ref inside the brackets, such as 482 or f1:93, to element tools, including "
            "type_text. Refs stay valid while the element stays in the same document and tab, "
            "even across observations. Element tools scroll their target into view first."
        )

    def render(self, snapshot: Snapshot) -> str:
        return render(snapshot)


class MetadataRenderer:
    """Render page and viewport facts as a compact observation."""

    def instructions(self) -> str:
        return (
            "Browser observations report the active page and its tab. "
            "The open-tab count covers tabs controlled by this session. "
            "Scroll position and remaining distance refer to the main page in CSS pixels."
        )

    def refs(self) -> None:
        return None

    def render(self, snapshot: Snapshot) -> str:
        return render_metadata(snapshot)


def screenshot_instructions(screenshots: Screenshots | None) -> str:
    if screenshots is None:
        return ""
    text = (
        "A screenshot is captured before each model step. Unchanged images may be reused."
        if screenshots.trigger == ScreenshotTrigger.EACH_STEP
        else "Use the screenshot tool to request a fresh image."
    )
    text += " Use click_at or drag_at to interact with an area shown in the image."
    if screenshots.marks is not None:
        text += (
            " In screenshots, each interactive element is outlined and labeled with its ref. "
            "Pass a visible ref to element tools."
        )
    return text
