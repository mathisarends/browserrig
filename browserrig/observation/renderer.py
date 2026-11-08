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
        text = (
            "Each observation starts with the page title, URL, open tabs, viewport size and "
            "scroll position, then any open modal and alerts. Interactive elements follow, one "
            'per line as `[ref] role "name" states value=... -> link`, grouped under landmark '
            'headers like [MAIN] or [DIALOG: name] and form or menu groups like <form "Login">. '
            "Headings (## Title) show where content sits. The viewport is listed first, "
            "followed by nearby controls above/below it, explicitly marked as previews. "
            "For iframe content, preview positions refer to that frame's visible viewport. "
            "Preview refs scroll into view and are hit-tested before input; they are not "
            "screenshot coordinates. Inner scroll targets show remaining distances in CSS "
            "pixels as scroll(up=..., down=..., left=..., right=...); use their ref with scroll "
            "to move that panel instead of the page. Descriptions give associated field guidance. "
            "A leading * marks elements that appeared since the previous observation. "
            "When little changed on the same page, an observation repeats only its header "
            "and the changed lines under their section headers (- removed, + added); the "
            "rest is as in the last complete observation. "
            "Elements covered by an overlay are counted, not listed. Modal dialogs can block "
            "controls outside them. Hidden file inputs remain available to upload_files; "
            "other hidden and inert controls are omitted. "
            "Likely cookie consent banners are marked [COOKIE BANNER] with a short visible "
            "text excerpt and their ordinary control refs, independently of the page-text "
            "budget. This detection is heuristic; choose whether to interact or navigate "
            "according to the task. "
            "Visible canvases are listed with their viewport-pixel bounds; their drawn content "
            "has no refs, so screenshot that region and point with click_at or drag_at. "
            "Before any image has been shown, coordinate tools take viewport CSS "
            "pixels, the same space as those bounds. Later text-only observations retain "
            "the newest shown image's coordinate space. "
        )
        if self.max_text_chars:
            text += "Observations include a bounded page-text excerpt. "
        elif self.sparse_text_chars:
            text += (
                "When the viewport holds few controls, observations add its visible text; "
                "otherwise use extract_content to read the page. "
            )
        else:
            text += "Observations omit page-text excerpts; use extract_content to read the page. "
        text += (
            "Every observation includes a screenshot; its pixels equal viewport CSS pixels."
            if screenshots.trigger == ScreenshotTrigger.EACH_STEP
            else "Screenshots are included only when requested; their pixels equal viewport "
            "CSS pixels."
        )
        text += (
            " A region screenshot shows only part of the viewport, optionally zoomed; its "
            "observation states the region, and coordinate tools then take that image's pixels."
        )
        if self.marks:
            text += (
                " In screenshots, each visible element is outlined with a colored dashed border "
                "and labeled with its ref. Links are blue, buttons green, text inputs purple."
            )
        return text

    def refs(self) -> str:
        return (
            "Pass the ref inside the brackets, such as 482 or f1:93, to element tools, including "
            "type_text. Refs stay valid while the element stays in the same document and tab, "
            "even across observations. Element interactions automatically use wheel input to "
            "bring targets into view before acting."
        )

    def render(self, snapshot: Snapshot) -> str:
        return render(snapshot)
