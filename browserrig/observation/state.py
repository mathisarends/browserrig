import asyncio
from dataclasses import dataclass, field

from harnessed.kernel import PluginScope

from browserrig.core import DocumentId, Region, TargetId

from .capture import CapturedObservation
from .models import CapturedImage


@dataclass
class BrowserPerceptionState:
    observation: CapturedObservation | None = None
    delivered_image: CapturedImage | None = None
    screenshot_requested: bool = False
    screenshot_region: Region | None = None
    screenshot_zoom: float = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    context: PluginScope | None = None
    generation: int = 0
    # Viewport size of each tab at its last step observation, to notice window resizes.
    viewports: dict[TargetId, tuple[float, float]] = field(default_factory=dict)


@dataclass
class ImageState:
    images: list[CapturedImage] = field(default_factory=list)
    # The last latest-screenshot note handed to the session.
    note: str = ""


@dataclass
class TextState:
    generation: int = 0
    # The last page state handed to the session, and whether the last request still showed it.
    sent_key: str | None = None
    sent_ref: str | None = None
    visible: bool = False
    # The last complete observation of each page (tab, document) with its ref, which later
    # ones of that page may list changes to while a request still includes it.
    bases: dict[tuple[TargetId, DocumentId, int, float, float], tuple[str, str]] = (
        field(default_factory=dict)
    )
    included: frozenset[str] = frozenset()
