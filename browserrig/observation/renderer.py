from dataclasses import dataclass
from typing import Protocol

from .config import Screenshots, ScreenshotTrigger
from .models import Snapshot
from .render import render


class Renderer(Protocol):
    def instructions(self, screenshots: Screenshots) -> str: ...
    def refs(self) -> str | None: ...
    def render(self, snapshot: Snapshot) -> str: ...


@dataclass(frozen=True)
class DomRenderer:
    max_text_chars: int = 0
    sparse_text_chars: int = 0
    marks: bool = True

    def instructions(self, screenshots: Screenshots) -> str:
        # The observation labels its own sections (previews, overlays, canvases, deltas);
        # this only explains what the labels cannot.
        text = (
            "Each observation starts with a page header, then lists interactive elements "
            'one per line as `[ref] role "name" states value=... -> link`, grouped under '
            'landmarks like [MAIN] and groups like <form "Login">. A leading * marks elements '
            "new since the previous observation. Inside iframes, above/below previews refer to "
            "the frame's viewport. An element with scroll(up=..., down=...) is an inner scroll "
            "container; use scroll_element(ref=...) for that panel and scroll_page for the page. "
            "Modal dialogs can block controls outside them. [COOKIE BANNER] detection is "
            "heuristic; choose whether to interact or navigate according to the task. "
            "Canvas content has no "
            "refs; screenshot it and point with click_at or drag_at. "
        )
        if self.max_text_chars:
            text += (
                "Visible text appears in reading order beside its controls, within a bounded "
                "text budget. Plain text has no action refs. A truncation marker applies "
                "to text at that position; later controls are still listed. "
            )
        elif self.sparse_text_chars:
            text += (
                "When the viewport holds few controls, observations add its visible text; "
                "otherwise extract_content saves it for targeted file reads. "
            )
        else:
            text += (
                "Observations omit page text; "
                "extract_content saves it for targeted file reads. "
            )
        if self.max_text_chars or self.sparse_text_chars:
            text += (
                "Links within prose use [label][ref]; pass that ref to element tools. "
            )
        text += (
            "Every observation includes a screenshot."
            if screenshots.trigger == ScreenshotTrigger.EACH_STEP
            else "Screenshots are included only when requested."
        )
        if self.marks:
            text += (
                " In screenshots, each element is outlined and labeled with its ref: "
                "links blue, buttons green, text inputs purple."
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
