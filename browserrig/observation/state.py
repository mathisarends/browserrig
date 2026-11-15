import asyncio
from dataclasses import dataclass, field
from typing import NamedTuple

from harnessed.kernel import PluginScope

from browserrig.core import DocumentId, Region, TargetId, ViewportSize

from .capture import CapturedObservation
from .models import CapturedImage


class PageView(NamedTuple):
    """A page as one observation saw it: its document, layout revision and viewport."""

    tab_id: TargetId
    document_id: DocumentId
    viewport_revision: int
    width: float
    height: float


class ObservedText(NamedTuple):
    """The plain text of an observation that later ones may list changes to."""

    text: str
    ref: str


@dataclass
class BrowserPerceptionState:
    observation: CapturedObservation | None = None
    delivered_image: CapturedImage | None = None
    screenshot_requested: bool = False
    screenshot_region: Region | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    context: PluginScope | None = None
    generation: int = 0
    # Viewport size of each tab at its last step observation, to notice window resizes.
    viewports: dict[TargetId, ViewportSize] = field(default_factory=dict)


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
    bases: dict[PageView, ObservedText] = field(default_factory=dict)
    included: frozenset[str] = frozenset()
