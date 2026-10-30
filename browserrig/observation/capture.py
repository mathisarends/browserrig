from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from browserrig.browser.images import screenshot
from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Bounds, Geometry, Point, Region
from browserrig.core.kinds import ObservationKind, ReadinessStatus
from browserrig.core.modes import DomMode
from browserrig.readiness.models import ReadinessReport

from .extraction import Extraction, extract
from .marks import annotate, blackout
from .models import Element, ElementFingerprint, PageFingerprint, Snapshot

# Longest side of a zoomed region image, to bound image tokens.
_MAX_REGION_SIDE = 2000


class Redaction(Protocol):
    """Hides known secret values, e.g. the Secrets plugin."""

    def redact[T](self, value: T) -> T: ...


async def capture(
    tab: Tab,
    mode: DomMode | CaptureStrategy,
    report: ReadinessReport,
    *,
    tabs: tuple[TabInfo, ...] = (),
    previous: Snapshot | None = None,
    region: Region | None = None,
    zoom: float = 1,
    screenshots: bool | None = None,
    cursor: Point | None = None,
    redaction: Redaction | None = None,
) -> Snapshot:
    """Observe `tab`. With `previous` from the same document, unseen elements get `new`.

    `region` crops a DOM-mode screenshot to a viewport area, magnified by `zoom`.
    `cursor` is where the browser's mouse rests in `tab`; screenshots mark it.
    `redaction` hides secrets in all text and blacks out elements showing one.
    """
    if isinstance(mode, DomMode):
        strategy = DomCapture(
            max_elements=mode.max_elements, max_text_chars=mode.max_text_chars, marks=mode.marks
        )
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
    content = await strategy.collect(
        tab, report, screenshots=screenshots, region=region, zoom=zoom, cursor=cursor
    )
    await tab.sync_document()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during capture; observe again before acting")
    page, image = content.page, content.image
    if redaction is not None:
        page, image = await _redact(page, image, content, redaction)
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
        fingerprint=_fingerprint(page, document_id),
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
    )


@dataclass(frozen=True, slots=True)
class CaptureContent:
    """`area` is the viewport region `image` shows, at `scale` image pixels per CSS pixel."""

    page: Extraction
    image: str | None = None
    geometry: Geometry | None = None
    area: Bounds | None = None
    scale: float = 1


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
        cursor: Point | None = None,
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
        cursor: Point | None = None,
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
            annotate,
            await screenshot(tab, geometry),
            marked,
            area,
            scale,
            cursor=cursor,
        )
        return CaptureContent(page=page, image=image, geometry=geometry, area=area, scale=scale)


async def _redact(
    page: Extraction, image: str | None, content: CaptureContent, redaction: Redaction
) -> tuple[Extraction, str | None]:
    """Redact page text before the snapshot and its fingerprint are built.

    Elements whose text holds a secret are blacked out in the image. An image without a
    known area is dropped rather than shown with a secret it might contain.
    """
    redacted = redaction.redact(page)
    if image is None or redacted is page:
        return redacted, image
    hidden = tuple(
        element.bounds
        for element, clean in zip(page.elements, redacted.elements, strict=True)
        if element.bounds is not None and clean is not element
    )
    if not hidden:
        return redacted, image
    if content.area is None:
        redacted.limitations = (*redacted.limitations, "Screenshot withheld: it may show a secret")
        return redacted, None
    return redacted, await asyncio.to_thread(blackout, image, hidden, content.area, content.scale)


def _mark_new(
    elements: tuple[Element, ...], previous: Snapshot | None, tab_id: str, document_id: str
) -> tuple[Element, ...]:
    if previous is None or previous.tab_id != tab_id or previous.document_id != document_id:
        return elements
    seen = {control.ref for control in (*previous.elements, *previous.offscreen)}
    if not seen:
        return elements
    return tuple(
        element if element.ref in seen else element.model_copy(update={"new": True})
        for element in elements
    )


def _fingerprint(page: Extraction, document_id: str) -> str:
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
    ).digest()
