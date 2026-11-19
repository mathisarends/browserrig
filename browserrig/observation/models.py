from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, SerializeAsAny

from browserrig.browser import TabInfo
from browserrig.core import (
    Bounds,
    Generation,
    Geometry,
    Options,
    Point,
    ReadinessStatus,
    StaleElement,
)


class Target(Options):
    """Something an agent can address by `ref` within one tab and document.

    A page model reports targets; subclasses add the model's own data. `bounds` use
    viewport CSS pixels. `new` marks targets absent from the previous observation.
    """

    ref: str
    role: str
    name: str
    bounds: Bounds | None = None
    in_viewport: bool = True
    new: bool = False


class PagePart(Options):
    """Model-specific observation data that a page model adds to a snapshot."""

    def refs(self) -> tuple[str, ...]:
        """Known refs that are not current targets, such as controls outside the viewport."""
        return ()

    def labels(self) -> tuple[str, ...]:
        """Short page labels such as headings, for heuristics that read any page model."""
        return ()

    def fingerprint(self, targets: tuple[Target, ...]) -> str:
        """Comparison data for this part, so unchanged pages can be recognized."""
        del targets
        return self.model_dump_json()


@dataclass(slots=True)
class PageContent:
    """What a page model observed: page metrics, targets and its own snapshot parts."""

    url: str
    title: str
    width: float
    height: float
    scroll_y: float
    page_height: float
    targets: tuple[Target, ...] = ()
    parts: tuple[PagePart, ...] = ()
    text: str = ""
    limitations: tuple[str, ...] = ()


class ScreenshotStatus(StrEnum):
    """Why an attempted observation has no image."""

    UNAVAILABLE = "unavailable"
    WITHHELD = "withheld"


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
    targets: tuple[SerializeAsAny[Target], ...] = ()
    parts: tuple[SerializeAsAny[PagePart], ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = Field(default=None, repr=False)
    screenshot_status: ScreenshotStatus | None = None
    # The viewport area the image shows; coordinate tools map image pixels through it.
    geometry: Geometry | None = None
    device_scale: float | None = None
    # Where the mouse rests, in viewport CSS pixels; None before it entered this tab.
    cursor: Point | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Resize generation at capture start, including for retained screenshots.
    viewport_revision: int = 0
    generation: Generation = Field(
        default_factory=lambda data: Generation(
            state=data["document_id"], layout=(data["viewport_revision"], 0)
        )
    )

    def target(self, ref: str) -> Target:
        for target in self.targets:
            if target.ref == ref:
                return target
        if any(ref in part.refs() for part in self.parts):
            raise StaleElement("Element is outside the viewport; scroll to it first")
        raise StaleElement(
            "Unknown element reference; use refs from the next observation"
        )

    def part[P: PagePart](self, kind: type[P]) -> P | None:
        """The part a page model of this kind added, if any."""
        return next((part for part in self.parts if isinstance(part, kind)), None)

    def known_refs(self) -> frozenset[str]:
        """Refs of targets and of known targets outside the viewport."""
        refs = {target.ref for target in self.targets}
        for part in self.parts:
            refs.update(part.refs())
        return frozenset(refs)


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
    viewport_revision: int = 0
    generation: Generation = Generation(state="")
    url: str = ""
    device_scale: float | None = None
    asset_id: str | None = None

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
            snapshot.viewport_revision,
            snapshot.generation,
            url=snapshot.url,
            device_scale=snapshot.device_scale,
        )


class TargetFingerprint(Options):
    role: str
    name: str
    in_viewport: bool = True


class PageFingerprint(Options):
    """Typed comparison data; target refs never affect equality."""

    url: str
    document_id: str
    text: str = ""
    targets: tuple[TargetFingerprint, ...] = ()
    parts: tuple[str, ...] = ()
    scroll_y: float

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()
