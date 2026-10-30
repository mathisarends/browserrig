from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from browserrig.core.geometry import Bounds, Geometry, Point
from browserrig.core.kinds import ElementOperation
from browserrig.core.options import Options


class ScriptArgs(Options):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ElementArgs(ScriptArgs):
    operation: ElementOperation
    value: str | bool | None = None
    clip: Bounds | None = None


class ScrollArgs(ScriptArgs):
    clip: Bounds | None = None


class OwnerScrollArgs(ScriptArgs):
    clip: Bounds | None = None
    target_bounds: Bounds


class CanvasArgs(ScriptArgs):
    selector: str
    loading_selector: str


class ContentArgs(ScriptArgs):
    max_chars: int


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


class DOMProbe(Options):
    loaded: bool
    body: bool
    quiet_ms: float
    width: float
    height: float


class CanvasProbe(Options):
    ready: bool
    geometry: Geometry | None = None
    reason: str = ""


class ContentExtraction(Options):
    url: str
    title: str
    markdown: str
    truncated: bool = False
    frames: int = 0


class PageFacts(Options):
    url: str
    title: str
    width: float
    height: float
    scroll_y: float
