import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field

from browserrig.browser import TabInfo
from browserrig.core import (
    Bounds,
    Geometry,
    Options,
    Point,
    ReadinessStatus,
    StaleElement,
)

type Tristate = bool | Literal["mixed"] | None
CHECKABLE_ROLES = frozenset(
    {"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"}
)


class Option(Options):
    label: str
    selected: bool = False
    disabled: bool = False


class ScrollInfo(Options):
    """Remaining wheel-scroll distances inside a control, in CSS pixels."""

    up: float = 0
    down: float = 0
    left: float = 0
    right: float = 0


class ElementRef(Options):
    """An opaque reference owned by a capture backend within one tab and document."""

    ref: str


class ElementInfo(ElementRef):
    """Observed target data, independent of how the backend finds the target."""

    order: int = 0
    role: str
    name: str
    tag: str = ""
    input_type: str = ""
    value: str | None = None
    placeholder: str = ""
    description: str = ""
    href: str = ""
    options: tuple[Option, ...] = ()
    section: str = ""
    group: str = ""
    in_viewport: bool = True
    outside_viewport: Literal["above", "below"] | None = None
    scroll: ScrollInfo | None = None
    covered: bool = False
    pinned: bool = False
    new: bool = False
    bounds: Bounds | None = None
    disabled: bool = False
    checked: Tristate = None
    selected: bool = False
    expanded: bool | None = None
    pressed: Tristate = None
    required: bool = False
    readonly: bool = False
    invalid: bool = False
    focused: bool = False
    has_popup: str = ""
    current: str = ""
    draggable: bool = False


class Element(ElementInfo):
    """A DOM target. Existing DOM refs stay valid while their node stays in its document."""

    frame_id: str
    backend_id: int
    tag: str


class Offscreen(ElementRef):
    """A DOM control outside the viewport, known by identity until scrolled in."""

    frame_id: str
    backend_id: int


class Heading(Options):
    level: int
    text: str
    frame_id: str
    order: int = 0
    in_viewport: bool = True
    outside_viewport: Literal["above", "below"] | None = None
    section: str = ""


class Modal(Options):
    role: str
    name: str


class CookieBanner(Options):
    """A likely visible consent UI, with the refs of its ordinary page controls."""

    name: str = ""
    text: str = ""
    refs: tuple[str, ...] = ()
    modal: bool = False


class Canvas(Options):
    """A visible canvas; its pixels have no element refs, so agents point with coordinates.

    `bounds` is the visible part in viewport CSS pixels. `ref` is set when the canvas is
    also listed as an interactive element.
    """

    frame_id: str
    bounds: Bounds
    name: str = ""
    ref: str = ""
    clipped: bool = False


@dataclass(slots=True)
class PageContent:
    """Captured page data shared by DOM and non-DOM strategies."""

    url: str
    title: str
    width: float
    height: float
    scroll_y: float
    page_height: float
    elements: tuple[ElementInfo, ...] = ()
    offscreen: tuple[ElementRef, ...] = ()
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    canvases: tuple[Canvas, ...] = ()
    text: str = ""
    limitations: tuple[str, ...] = ()
    cookie_banners: tuple[CookieBanner, ...] = ()


class Snapshot(Options):
    id: str
    tab_id: str
    document_id: str
    url: str
    title: str
    readiness: ReadinessStatus
    readiness_reason: str = ""
    width: float
    height: float
    scroll_y: float
    page_height: float = 0
    fingerprint: str
    tabs: tuple[TabInfo, ...] = ()
    text: str = ""
    # Visible controls and nearby previews are described; distant controls keep identities.
    elements: tuple[Element | ElementInfo, ...] = ()
    offscreen: tuple[Offscreen | ElementRef, ...] = Field(default=(), repr=False)
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    cookie_banners: tuple[CookieBanner, ...] = ()
    canvases: tuple[Canvas, ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = Field(default=None, repr=False)
    # The viewport area the image shows; coordinate tools map image pixels through it.
    geometry: Geometry | None = None
    # Where the mouse rests, in viewport CSS pixels; None before it entered this tab.
    cursor: Point | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def element(self, ref: str) -> ElementInfo:
        for element in self.elements:
            if element.ref == ref:
                return element
        if any(control.ref == ref for control in self.offscreen):
            raise StaleElement("Element is outside the viewport; scroll to it first")
        raise StaleElement(
            "Unknown element reference; use refs from the next observation"
        )


@dataclass(frozen=True, slots=True)
class CapturedImage:
    """An image keeps its coordinate space even after a later text-only observation."""

    id: str
    browser_id: str
    tab_id: str
    document_id: str
    captured_at: datetime
    image: str
    width: float
    height: float
    geometry: Geometry | None

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot, browser_id: str) -> Self:
        if snapshot.image is None:
            raise ValueError("Snapshot has no image")
        return cls(
            snapshot.id,
            browser_id,
            snapshot.tab_id,
            snapshot.document_id,
            snapshot.captured_at,
            snapshot.image,
            snapshot.width,
            snapshot.height,
            snapshot.geometry,
        )


class ElementFingerprint(Options):
    role: str
    name: str
    description: str = ""
    scroll: ScrollInfo | None = None
    in_viewport: bool = True
    value: str | None
    disabled: bool
    checked: Tristate = None
    expanded: bool | None = None
    selected: bool = False
    pressed: Tristate = None


class PageFingerprint(Options):
    """Typed comparison data; element refs never affect equality."""

    url: str
    document_id: str
    text: tuple[str, ...]
    elements: tuple[ElementFingerprint, ...]
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    cookie_banners: tuple[CookieBanner, ...] = ()
    scroll_y: float

    def digest(self) -> str:
        data = self.model_dump_json(exclude={"cookie_banners": {"__all__": {"refs"}}})
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
