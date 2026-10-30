from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from browserrig.browser.images import screenshot
from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, Geometry, Region
from browserrig.core.kinds import ObservationKind, ReadinessStatus
from browserrig.core.modes import CanvasMode, DomMode, ObservationMode
from browserrig.readiness.models import ReadinessReport
from browserrig.scripts import PAGE_FACTS

from .extraction import Extraction, extract
from .marks import annotate
from .models import Element, ElementFingerprint, PageFingerprint, Snapshot
from .regions import CanvasRegion, CaptureRegion

# Longest side of a zoomed region image, to bound image tokens.
_MAX_REGION_SIDE = 2000


async def capture(
    tab: Tab,
    mode: ObservationMode | CaptureStrategy,
    report: ReadinessReport,
    *,
    tabs: tuple[TabInfo, ...] = (),
    previous: Snapshot | None = None,
    region: Region | None = None,
    zoom: float = 1,
    screenshots: bool | None = None,
) -> Snapshot:
    """Observe `tab`. With `previous` from the same document, unseen elements get `new`.

    `region` crops a DOM-mode screenshot to a viewport area, magnified by `zoom`.
    """
    if isinstance(mode, (DomMode, CanvasMode)):
        strategy = capture_for_mode(mode)
        screenshots = mode.screenshots if screenshots is None else screenshots
    else:
        strategy = mode
        screenshots = False if screenshots is None else screenshots
    snapshot_id = uuid4().hex
    if tab.dialog:
        return Snapshot(
            id=snapshot_id,
            tab_id=tab.id,
            document_id=tab.document_id,
            url=tab.url,
            title=tab.title,
            mode=strategy.kind,
            readiness=ReadinessStatus.BLOCKED,
            width=0,
            height=0,
            scroll_y=0,
            fingerprint="dialog",
            tabs=tabs,
            text=f"Open {tab.dialog[0]} dialog: {tab.dialog[1]}",
        )
    await tab.sync_document()
    document_id = tab.document_id
    content = await strategy.collect(tab, report, screenshots=screenshots, region=region, zoom=zoom)
    await tab.sync_document()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during capture; observe again before acting")
    page = content.page
    elements = _mark_new(page.elements, previous, tab.id, document_id)
    return Snapshot(
        id=snapshot_id,
        tab_id=tab.id,
        document_id=document_id,
        url=page.url,
        title=page.title,
        width=page.width,
        height=page.height,
        scroll_y=page.scroll_y,
        page_height=page.page_height,
        mode=strategy.kind,
        readiness=report.status,
        fingerprint=_fingerprint(page, document_id, content.image_digest),
        tabs=tabs,
        text=page.text,
        elements=elements,
        headings=page.headings,
        alerts=page.alerts,
        modal=page.modal,
        canvases=page.canvases,
        limitations=page.limitations,
        image=content.image,
        geometry=content.geometry,
    )


@dataclass(frozen=True, slots=True)
class CaptureContent:
    page: Extraction
    image: str | None = None
    image_digest: str | None = None
    geometry: Geometry | None = None


class CaptureStrategy(Protocol):
    """Collect content; the shared capture runner owns dialogs and document coherence.

    Implementations are reusable configuration. Keep per-observation state local.
    `provides_dom_refs` promises that collected refs support Observe.element().
    """

    kind: ObservationKind
    provides_dom_refs: bool

    async def collect(  # pylint: disable=unused-argument
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
    ) -> CaptureContent: ...


class DomCapture:
    kind = ObservationKind.DOM
    provides_dom_refs = True

    def __init__(
        self, *, max_elements: int | None = None, max_text_chars: int = 0, marks: bool = True
    ) -> None:
        self._mode = DomMode(max_elements=max_elements, max_text_chars=max_text_chars, marks=marks)

    @property
    def max_text_chars(self) -> int:
        return self._mode.max_text_chars

    @property
    def marks(self) -> bool:
        return self._mode.marks

    async def collect(  # pylint: disable=unused-argument
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
    ) -> CaptureContent:
        frames = await tab.frames()
        page = await extract(
            frames, max_elements=self._mode.max_elements, max_text=self._mode.max_text_chars
        )
        page.limitations = tuple(dict.fromkeys((*tab.frame_limitations, *page.limitations)))
        if not screenshots:
            return CaptureContent(page=page)
        viewport = frames[0].visible
        assert viewport is not None
        marked = page.elements if self._mode.marks else ()
        geometry = None
        if region is not None:
            geometry = region.capture(viewport, zoom, _MAX_REGION_SIDE)
            if geometry is None:
                page.limitations = (
                    *page.limitations,
                    "Screenshot region is outside the viewport; showing the full viewport",
                )
        if geometry is None:
            area, scale = Bounds(x=0, y=0, width=viewport.width, height=viewport.height), 1.0
        else:
            area = Bounds(x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height)
            scale = geometry.scale
        image = await asyncio.to_thread(
            annotate, await screenshot(tab, geometry), marked, area, scale
        )
        return CaptureContent(page=page, image=image, geometry=geometry)


class CanvasCapture:
    kind = ObservationKind.CANVAS
    provides_dom_refs = False

    def __init__(self, *, region: CaptureRegion | None = None) -> None:
        self.region = region or CanvasRegion()

    async def collect(  # pylint: disable=unused-argument
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
    ) -> CaptureContent:
        facts = await (await tab.main_frame()).run(PAGE_FACTS)
        geometry = await self.region.resolve(tab) if screenshots else None
        image = await screenshot(tab, geometry) if screenshots else None
        page = Extraction(
            url=facts.url,
            title=facts.title,
            width=facts.width,
            height=facts.height,
            scroll_y=facts.scroll_y,
            page_height=0,
        )
        return CaptureContent(
            page=page,
            image=image,
            image_digest=hashlib.sha256(image.encode()).hexdigest() if image else None,
            geometry=geometry,
        )


def capture_for_mode(mode: ObservationMode) -> CaptureStrategy:
    """Compatibility adapter for the original mode configuration."""
    if isinstance(mode, DomMode):
        return DomCapture(
            max_elements=mode.max_elements, max_text_chars=mode.max_text_chars, marks=mode.marks
        )
    return CanvasCapture(region=CanvasRegion(selector=mode.selector))


def _mark_new(
    elements: tuple[Element, ...], previous: Snapshot | None, tab_id: str, document_id: str
) -> tuple[Element, ...]:
    if previous is None or previous.tab_id != tab_id or previous.document_id != document_id:
        return elements
    if not previous.elements:
        return elements
    seen = {element.ref for element in previous.elements}
    return tuple(
        element if element.ref in seen else element.model_copy(update={"new": True})
        for element in elements
    )


def _fingerprint(page: Extraction, document_id: str, image_digest: str | None) -> str:
    return PageFingerprint(
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
        image_digest=image_digest,
    ).digest()
