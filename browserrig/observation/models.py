from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from browserrig.browser.models import TabInfo
from browserrig.core.errors import StaleElement
from browserrig.core.geometry import Bounds, Geometry
from browserrig.core.kinds import ObservationKind, ReadinessStatus
from browserrig.core.options import Options

type Tristate = bool | Literal["mixed"] | None


class Option(Options):
    label: str
    selected: bool = False
    disabled: bool = False


class Element(Options):
    """One interactive element. `ref` stays valid while the element stays in its document."""

    ref: str
    frame_id: str
    backend_id: int
    order: int = 0
    role: str
    name: str
    tag: str
    input_type: str = ""
    value: str | None = None
    placeholder: str = ""
    href: str = ""
    options: tuple[Option, ...] = ()
    section: str = ""
    group: str = ""
    in_viewport: bool = True
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


class Offscreen(Options):
    """A control outside the viewport, known only by identity until it is scrolled in."""

    ref: str
    frame_id: str
    backend_id: int


class Heading(Options):
    level: int
    text: str
    frame_id: str
    order: int = 0
    in_viewport: bool = True
    section: str = ""


class Modal(Options):
    role: str
    name: str


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


class Snapshot(Options):
    id: str
    tab_id: str
    document_id: str
    url: str
    title: str
    mode: ObservationKind
    readiness: ReadinessStatus
    width: float
    height: float
    scroll_y: float
    page_height: float = 0
    fingerprint: str
    tabs: tuple[TabInfo, ...] = ()
    text: str = ""
    # Only controls the viewport shows are described; the rest are known by identity.
    elements: tuple[Element, ...] = ()
    offscreen: tuple[Offscreen, ...] = Field(default=(), repr=False)
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    canvases: tuple[Canvas, ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = Field(default=None, repr=False)
    # The viewport area the image shows; coordinate tools map image pixels through it.
    geometry: Geometry | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def element(self, ref: str) -> Element:
        for element in self.elements:
            if element.ref == ref:
                return element
        if any(control.ref == ref for control in self.offscreen):
            raise StaleElement("Element is outside the viewport; scroll to it first")
        raise StaleElement("Unknown element reference; observe again")


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
    def from_snapshot(cls, snapshot: Snapshot, browser_id: str) -> CapturedImage:
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
    scroll_y: float
    image_digest: str | None = None

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()
