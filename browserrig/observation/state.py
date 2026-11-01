import asyncio
from dataclasses import dataclass, field

from browserrig.core import DocumentId, Region, TargetId

from .models import CapturedImage, Snapshot


@dataclass
class ObserveState:
    snapshot: Snapshot | None = None
    delivered_image: CapturedImage | None = None
    screenshot_requested: bool = False
    screenshot_region: Region | None = None
    screenshot_zoom: float = 1
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # The last page state handed to the session, and whether the last request still showed it.
    sent_key: str | None = None
    sent_ref: str | None = None
    visible: bool = False
    # The last complete observation of each page (tab, document) with its ref, which later
    # ones of that page may list changes to while a request still includes it.
    bases: dict[tuple[TargetId, DocumentId], tuple[str, str]] = field(
        default_factory=dict
    )
    included: frozenset[str] = frozenset()


@dataclass
class ImageState:
    images: list[CapturedImage] = field(default_factory=list)
    # The last latest-screenshot note handed to the session.
    note: str = ""
