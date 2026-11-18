from dataclasses import dataclass

from browserrig.core import Options, ViewportSize


class TabInfo(Options):
    id: str
    url: str
    title: str
    active: bool = False


@dataclass(frozen=True, slots=True)
class PageLayout:
    """Layout viewport and main document scroll measurements in CSS pixels."""

    viewport: ViewportSize
    scroll_y: float
    page_height: float
