import hashlib

from pydantic import Field

from browserrig.browser.config import Options
from browserrig.browser.errors import StaleElement
from browserrig.browser.geometry import Bounds
from browserrig.browser.models import Geometry
from browserrig.readiness.models import ReadinessStatus

from .config import ObservationKind


class Element(Options):
    ref: str
    in_viewport: bool = True
    mark: int | None = None
    frame_id: str
    index: int
    role: str
    name: str
    tag: str
    input_type: str = ""
    value: str | None = None
    disabled: bool = False
    checked: bool | None = None
    draggable: bool = False
    options: tuple[str, ...] = ()
    bounds: Bounds | None = None


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
    fingerprint: str
    text: str = ""
    elements: tuple[Element, ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = Field(default=None, repr=False)
    geometry: Geometry | None = None

    def element(self, ref: str) -> Element:
        for element in self.elements:
            if element.ref == ref:
                return element
        raise StaleElement("Unknown or expired element reference; observe again")


class PageFacts(Options):
    url: str
    title: str
    width: float
    height: float
    scroll_y: float


class ExtractedElement(Options):
    index: int
    in_viewport: bool
    role: str
    name: str
    tag: str
    input_type: str = ""
    value: str | None = None
    disabled: bool = False
    checked: bool | None = None
    draggable: bool = False
    options: tuple[str, ...] = ()
    bounds: Bounds
    x: float
    y: float


class DOMExtraction(PageFacts):
    text: str
    elements: tuple[ExtractedElement, ...]
    truncated: bool = False


class ElementFingerprint(Options):
    role: str
    name: str
    in_viewport: bool = True
    value: str | None
    disabled: bool
    checked: bool | None = None


class PageFingerprint(Options):
    """Typed comparison data; ephemeral element refs never affect equality."""

    url: str
    document_id: str
    text: tuple[str, ...]
    elements: tuple[ElementFingerprint, ...]
    scroll_y: float
    image_digest: str | None = None

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()
