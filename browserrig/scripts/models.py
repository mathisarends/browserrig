from typing import Any

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from browserrig.core import Bounds, ElementOperation, Options, Point


class ScriptArgs(Options):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class OverlayArgs(ScriptArgs):
    operation: str
    id: str = ""
    data: Any = None
    visible: bool = True


class ElementArgs(ScriptArgs):
    operation: ElementOperation
    value: str | bool | None = None
    clip: Bounds | None = None
    # Preferred spot for `point`, as fractions of the element's visible box.
    aim: tuple[float, float] | None = None


class ScrollArgs(ScriptArgs):
    clip: Bounds | None = None
    apply: bool = False


class SelectOptionsArgs(ScriptArgs):
    values: tuple[str, ...]
    apply: bool = False


class SelectedOption(Options):
    label: str
    value: str


class SelectionResult(Options):
    selected: tuple[SelectedOption, ...]
    verified: bool
    reason: str = ""


class TargetScrollArgs(ScriptArgs):
    delta_x: float = 0
    delta_y: float = 0
    page: bool = False


class TargetScrollResult(Options):
    before: Point
    after: Point
    blocked: bool = False
    scrollable: bool = True


class UploadArgs(ScriptArgs):
    count: int


class TextState(Options):
    value: str
    start: int | None = None
    end: int | None = None


class OwnerScrollArgs(ScriptArgs):
    clip: Bounds | None = None
    target_bounds: Bounds
    apply: bool = False


class ContentArgs(ScriptArgs):
    max_chars: int
    main_only: bool = False
    # Links on this origin are shortened to paths.
    origin: str = ""


class FindArgs(ScriptArgs):
    # Alternative wordings searched together; their matches share one page-order numbering.
    queries: tuple[str, ...] = ()
    # One find-bar session; typing reruns the search and reuses the page text within it.
    session: str = ""
    # The match, counted in this frame, shown as current; -1 for none.
    active: int = -1
    # The window of matches described with context.
    start: int = 0
    count: int = 0
    # Open collapsed sections around the current match and scroll it into view.
    reveal: bool = False
    clip: Bounds | None = None
    # Remove the find markers.
    close: bool = False


class OwnerHitsArgs(ScriptArgs):
    points: tuple[tuple[float, float], ...]


class CursorArgs(ScriptArgs):
    x: float
    y: float


class SeedArgs(ScriptArgs):
    clickable: tuple[bool, ...]


class ScrollPlan(Point):
    delta_x: float
    delta_y: float
    scroll_x: float
    scroll_y: float
    after_x: float | None = None
    after_y: float | None = None
    container: str = "page"


class DOMProbe(Options):
    loaded: bool
    body: bool
    quiet_ms: float
    width: float
    height: float
    unobserved_frames: int = 0
    animations: int = 0
    busy: bool = False
    limited: bool = False


class ContentExtraction(Options):
    url: str
    title: str
    markdown: str
    truncated: bool = False
    frames: int = 0
    # Whether only the main landmark was read.
    main: bool = False
    # Whether site header, navigation and footer were left out of a page without a main one.
    chrome: bool = False
    limited: bool = False
    # The visible part of what was read, in viewport CSS pixels.
    region: Bounds | None = None


class FoundText(Options):
    before: str
    text: str
    after: str
    heading: str = ""
    # Inside a closed section; it opens when this match becomes current.
    collapsed: bool = False


class FoundMark(Options):
    index: int
    # Frame-local viewport rectangles as (x, y, width, height).
    rects: tuple[tuple[float, float, float, float], ...]


class FindResult(Options):
    total: int
    # Matches per query, in the order of `queries`.
    counts: tuple[int, ...] = ()
    items: tuple[FoundText, ...] = ()
    marks: tuple[FoundMark, ...] = ()
    scrolled: bool = False


class PageFacts(Options):
    url: str
    title: str
    width: float
    height: float
    scroll_y: float


class TabStrip(Options):
    """The document title and best icon URL; `icon` is empty for non-web pages."""

    title: str
    icon: str


class SecretFieldArgs(ScriptArgs):
    mask: bool = False


class SecretFocusArgs(ScriptArgs):
    start: bool = False


class SecretField(Options):
    origin: str
    focused: bool


class SecretFocus(Options):
    origins: tuple[str, ...]
    cross_origin: bool
    editable: bool
    same: bool
