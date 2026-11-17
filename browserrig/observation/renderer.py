from dataclasses import dataclass
from typing import Protocol

from .config import PageText, Screenshots, ScreenshotTrigger
from .models import Snapshot
from .render import render


class Renderer(Protocol):
    def instructions(self) -> str:
        """Explain how to read the text projection."""

    def refs(self) -> str | None:
        """Describe how to use target refs, or None when refs are unavailable."""

    def render(self, snapshot: Snapshot) -> str:
        """Format a snapshot as the observation text supplied to the agent."""


@dataclass(frozen=True)
class DomRenderer:
    # Describes the text a capture supplies; custom captures promise none by default.
    text: PageText = PageText.OFF
    landmarks: bool = True

    def instructions(self) -> str:
        # The observation labels its own sections (previews, overlays, canvases, deltas);
        # this only explains what the labels cannot.
        groups = (
            'landmarks like [MAIN] and groups like <form "Login">'
            if self.landmarks
            else 'groups like <form "Login">'
        )
        text = (
            "Each observation starts with a page header, then lists interactive elements "
            'one per line as `[ref] role "name" states value=... -> link`, grouped under '
            f"{groups}. A leading * marks elements "
            "new since the previous observation. Inside iframes, above/below previews refer to "
            "the frame's viewport. An element with scroll(up=..., down=...) is an inner scroll "
            "container; use scroll_element(ref=...) for that panel and scroll_page for the page. "
            "multiple marks multi-select controls; options show * for selected entries "
            "and explicit values when available. Radio IDs, values and selection_group "
            "are raw page metadata, not interpreted ratings. "
            "Modal dialogs can block controls outside them. [COOKIE BANNER] detection is "
            "heuristic; choose whether to interact or navigate according to the task. "
            "Canvas content has no refs. "
        )
        if self.text == PageText.INLINE:
            text += (
                "Visible text appears in reading order beside its controls, within a bounded "
                "text budget. Plain text has no action refs. A truncation marker applies "
                "to text at that position; later controls are still listed. "
            )
        elif self.text == PageText.SPARSE:
            text += (
                "When the viewport holds few controls, observations add its visible text; "
                "otherwise search_page finds it. "
            )
        else:
            text += "Observations omit page text; search_page finds it. "
        if self.text != PageText.OFF:
            text += (
                "Links within prose use [label][ref]; pass that ref to element tools. "
            )
        return text

    def refs(self) -> str:
        return (
            "Pass the ref inside the brackets, such as 482 or f1:93, to element tools, including "
            "type_text. Refs stay valid while the element stays in the same document and tab, "
            "even across observations. Element tools scroll their target into view first."
        )

    def render(self, snapshot: Snapshot) -> str:
        return render(snapshot)


def screenshot_instructions(screenshots: Screenshots | None) -> str:
    if screenshots is None:
        return ""
    text = (
        "Every observation includes a screenshot."
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
