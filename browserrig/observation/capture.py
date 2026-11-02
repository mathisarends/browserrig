from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import uuid4

from cdpify.exceptions import CDPCommandError
from pydantic import Field

from browserrig.browser import Tab, TabInfo, screenshot
from browserrig.core import (
    Bounds,
    BrowserError,
    Geometry,
    Options,
    Point,
    ReadinessStatus,
    Region,
)
from browserrig.readiness import ReadinessReport

from .extraction import extract
from .handle import DomReferences
from .marks import annotate, blackout
from .models import (
    ElementFingerprint,
    ElementInfo,
    PageContent,
    PageFingerprint,
    Snapshot,
)
from .references import References

# Longest side of a zoomed region image, to bound image tokens.
_MAX_REGION_SIDE = 2000


class Redaction(Protocol):
    """Hides known secret values, e.g. the Secrets plugin."""

    def redact[T](self, value: T) -> T: ...


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    """Serializable observed data paired with its per-observation reference resolver."""

    snapshot: Snapshot
    references: References


async def capture(
    tab: Tab,
    strategy: CaptureStrategy,
    report: ReadinessReport,
    *,
    tabs: tuple[TabInfo, ...] = (),
    previous: Snapshot | None = None,
    region: Region | None = None,
    zoom: float = 1,
    screenshots: bool = False,
    cursor: Point | None = None,
    redaction: Redaction | None = None,
) -> Snapshot:
    """Capture a serializable snapshot; Observe also retains its reference resolver."""
    observation = await capture_observation(
        tab,
        strategy,
        report,
        tabs=tabs,
        previous=previous,
        region=region,
        zoom=zoom,
        screenshots=screenshots,
        cursor=cursor,
        redaction=redaction,
    )
    return observation.snapshot


async def capture_observation(
    tab: Tab,
    strategy: CaptureStrategy,
    report: ReadinessReport,
    *,
    tabs: tuple[TabInfo, ...] = (),
    previous: Snapshot | None = None,
    region: Region | None = None,
    zoom: float = 1,
    screenshots: bool = False,
    cursor: Point | None = None,
    redaction: Redaction | None = None,
) -> CapturedObservation:
    """Observe `tab`. With `previous` from the same document, unseen elements get `new`.

    `region` crops a screenshot to a viewport area, magnified by `zoom`.
    `cursor` is where the browser's mouse rests in `tab`; screenshots mark it.
    `redaction` hides secrets in all text and blacks out elements showing one.
    """
    snapshot_id = uuid4().hex
    if tab.dialog:
        snapshot = Snapshot(
            id=snapshot_id,
            tab_id=tab.id,
            document_id=tab.document_id,
            url=tab.url,
            title=tab.title,
            readiness=ReadinessStatus.BLOCKED,
            width=0,
            height=0,
            scroll_y=0,
            fingerprint="dialog",
            tabs=tabs,
            text=f"Open {tab.dialog[0]} dialog: {tab.dialog[1]}",
            cursor=cursor,
        )
        return CapturedObservation(snapshot, DomReferences())
    try:
        # A pending renderer must not hold the next model iteration indefinitely
        # after the readiness budget has already expired.
        async with asyncio.timeout(1 if report.timed_out else None):
            await tab.sync_document()
            document_id = tab.document_id
            content = await strategy.collect(
                tab,
                report,
                screenshots=screenshots,
                region=region,
                zoom=zoom,
                cursor=cursor,
            )
            await tab.sync_document()
            if tab.document_id != document_id:
                raise BrowserError(
                    "Document changed during capture; act on the next observation"
                )
    except (BrowserError, CDPCommandError, TimeoutError):
        if not report.timed_out:
            raise
        snapshot = Snapshot(
            id=snapshot_id,
            tab_id=tab.id,
            document_id=tab.document_id,
            url=tab.url,
            title=tab.title,
            readiness=report.status,
            readiness_reason=report.reason,
            width=0,
            height=0,
            scroll_y=0,
            fingerprint=f"readiness:{report.id}",
            tabs=tabs,
            text="The page is still loading. Observe again before using page controls.",
        )
        return CapturedObservation(snapshot, DomReferences())
    page, image = content.page, content.image
    if redaction is not None:
        page, image = await _redact(page, image, content, redaction)
    refs = [element.ref for element in (*page.elements, *page.offscreen)]
    if len(set(refs)) != len(refs):
        raise BrowserError("Capture returned duplicate element refs")
    elements = _mark_new(page.elements, previous, tab.id, document_id)
    snapshot = Snapshot(
        id=snapshot_id,
        tab_id=tab.id,
        document_id=document_id,
        url=page.url,
        title=page.title,
        width=page.width,
        height=page.height,
        scroll_y=page.scroll_y,
        page_height=page.page_height,
        readiness=report.status,
        readiness_reason=report.reason,
        fingerprint=content.fingerprint
        if content.fingerprint is not None
        else _fingerprint(page, document_id),
        tabs=tabs,
        text=page.text,
        elements=elements,
        offscreen=page.offscreen,
        headings=page.headings,
        alerts=page.alerts,
        modal=page.modal,
        canvases=page.canvases,
        limitations=page.limitations,
        image=image,
        geometry=content.geometry,
        cursor=cursor,
    )
    references = (
        content.references if content.references is not None else DomReferences()
    )
    return CapturedObservation(snapshot, references)


@dataclass(frozen=True, slots=True)
class CaptureContent:
    """`area` is the viewport region `image` shows, at `scale` image pixels per CSS pixel.

    `fingerprint=None` uses the runner's DOM semantic fingerprint.
    """

    page: PageContent
    image: str | None = None
    geometry: Geometry | None = None
    area: Bounds | None = None
    scale: float = 1
    fingerprint: str | None = None
    references: References | None = None


class CaptureStrategy(Protocol):
    """Collect content; the shared capture runner owns dialogs and document coherence.

    Implementations are reusable configuration. Keep per-observation state local.
    Set CaptureContent.references for non-DOM refs. The default resolves DOM addresses.
    """

    async def collect(  # pylint: disable=unused-argument
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
        cursor: Point | None = None,
    ) -> CaptureContent: ...


class DomCapture(Options):
    max_elements: int | None = Field(default=None, ge=1, le=50000)
    max_text_chars: int = Field(default=0, ge=0, le=100000)
    # Show visible text on pages with fewer than five named controls.
    sparse_text_chars: int = Field(default=1500, ge=0, le=100000)
    marks: bool = True

    async def collect(  # pylint: disable=unused-argument
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
        cursor: Point | None = None,
    ) -> CaptureContent:
        frames = await tab.frames()
        page = await extract(
            frames,
            max_elements=self.max_elements,
            max_text=self.max_text_chars,
            sparse_text=self.sparse_text_chars,
        )
        page.limitations = tuple(
            dict.fromkeys((*tab.frame_limitations, *page.limitations))
        )
        if not screenshots:
            return CaptureContent(page=page)
        viewport = frames[0].visible
        assert viewport is not None
        marked = page.elements if self.marks else ()
        geometry = None
        if region is not None:
            geometry = region.capture(viewport, zoom, _MAX_REGION_SIDE)
            if geometry is None:
                page.limitations = (
                    *page.limitations,
                    "Screenshot region is outside the viewport; showing the full viewport",
                )
        if geometry is None:
            area, scale = (
                Bounds(x=0, y=0, width=viewport.width, height=viewport.height),
                1.0,
            )
        else:
            area = Bounds(
                x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height
            )
            scale = geometry.scale
        image = await asyncio.to_thread(
            annotate,
            await screenshot(tab, geometry),
            marked,
            area,
            scale,
            cursor=cursor,
        )
        return CaptureContent(
            page=page, image=image, geometry=geometry, area=area, scale=scale
        )


async def _redact(
    page: PageContent, image: str | None, content: CaptureContent, redaction: Redaction
) -> tuple[PageContent, str | None]:
    """Redact page text before the snapshot and its fingerprint are built.

    Elements whose text holds a secret are blacked out in the image. Withhold the image
    when a secret also occurs in page text or in an element without known bounds.
    """
    redacted = redaction.redact(page)
    if image is None or redacted is page:
        return redacted, image
    changed = tuple(
        element
        for element, clean in zip(page.elements, redacted.elements, strict=True)
        if clean is not element
    )
    unlocated = replace(page, elements=redacted.elements) != redacted or any(
        element.bounds is None for element in changed
    )
    if content.area is None or unlocated:
        redacted.limitations = (
            *redacted.limitations,
            "Screenshot withheld: it may show a secret",
        )
        return redacted, None
    return redacted, await asyncio.to_thread(
        blackout,
        image,
        tuple(element.bounds for element in changed if element.bounds is not None),
        content.area,
        content.scale,
    )


def _mark_new(
    elements: tuple[ElementInfo, ...],
    previous: Snapshot | None,
    tab_id: str,
    document_id: str,
) -> tuple[ElementInfo, ...]:
    if (
        previous is None
        or previous.tab_id != tab_id
        or previous.document_id != document_id
    ):
        return elements
    seen = {control.ref for control in (*previous.elements, *previous.offscreen)}
    if not seen:
        return elements
    return tuple(
        element if element.ref in seen else element.model_copy(update={"new": True})
        for element in elements
    )


def _fingerprint(page: PageContent, document_id: str) -> str:
    fingerprint = PageFingerprint(
        url=page.url,
        document_id=document_id,
        text=(page.text,) if page.text else (),
        scroll_y=page.scroll_y,
        elements=tuple(
            ElementFingerprint(
                role=element.role,
                name=element.name,
                in_viewport=element.in_viewport,
                value=element.value,
                disabled=element.disabled,
                checked=element.checked,
                expanded=element.expanded,
                selected=element.selected,
                pressed=element.pressed,
            )
            for element in page.elements
        ),
        alerts=page.alerts,
        modal=page.modal,
    )
    return fingerprint.digest()
