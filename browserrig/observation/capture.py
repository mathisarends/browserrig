from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import uuid4

from cdpify import CDPCommandError
from harnessed.tracing import traced

from browserrig.browser import Tab, TabInfo
from browserrig.core import (
    Bounds,
    BrowserError,
    Geometry,
    Point,
    ReadinessStatus,
    Region,
    StaleElement,
)
from browserrig.readiness import ReadinessReport

from .flow import semantic_text
from .marks import blackout
from .models import (
    ElementFingerprint,
    ElementInfo,
    PageContent,
    PageFingerprint,
    Snapshot,
)
from .references import EmptyReferences, References

# Both attempts share this budget; an exhausted readiness wait gets only one second.
_CAPTURE_SECONDS = 10


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
    """Capture a serializable snapshot; BrowserPerception also retains its reference resolver."""
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


@traced
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
    # A resize while collecting leaves the whole capture outdated, including its image.
    viewport_revision = tab.viewport_revision
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
            viewport_revision=viewport_revision,
            tabs=tabs,
            text=f"Open {tab.dialog[0]} dialog: {tab.dialog[1]}",
            cursor=cursor,
        )
        return CapturedObservation(snapshot, EmptyReferences())
    try:
        content, document_id = await _collect(
            tab,
            strategy,
            report,
            screenshots=screenshots,
            region=region,
            zoom=zoom,
            cursor=cursor,
        )
    except (BrowserError, CDPCommandError, TimeoutError) as error:
        if not report.timed_out:
            if isinstance(error, TimeoutError):
                raise BrowserError("Page capture timed out; observe again") from error
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
            viewport_revision=viewport_revision,
            tabs=tabs,
            text="The page is still loading. Observe again before using page controls.",
        )
        return CapturedObservation(snapshot, EmptyReferences())
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
        readiness=report.status
        if document_id == report.document_id
        else ReadinessStatus.DEGRADED,
        readiness_reason=report.reason
        if document_id == report.document_id
        else "Document changed during capture; readiness has not been confirmed.",
        fingerprint=content.fingerprint
        if content.fingerprint is not None
        else _fingerprint(page, document_id),
        tabs=tabs,
        text=page.text,
        content=page.content,
        elements=elements,
        offscreen=page.offscreen,
        headings=page.headings,
        alerts=page.alerts,
        modal=page.modal,
        cookie_banners=page.cookie_banners,
        canvases=page.canvases,
        limitations=page.limitations,
        image=image,
        geometry=content.geometry,
        cursor=cursor,
        viewport_revision=viewport_revision,
    )
    references = (
        content.references if content.references is not None else EmptyReferences()
    )
    return CapturedObservation(snapshot, references)


@dataclass(frozen=True, slots=True)
class CaptureContent:
    """`area` is the viewport region `image` shows, at `scale` image pixels per CSS pixel.

    `fingerprint=None` uses the runner's semantic PageContent fingerprint.
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
    Supply CaptureContent.references when targets exist. The default resolves no refs.
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


async def _collect(
    tab: Tab,
    strategy: CaptureStrategy,
    report: ReadinessReport,
    *,
    screenshots: bool,
    region: Region | None,
    zoom: float,
    cursor: Point | None,
) -> tuple[CaptureContent, str]:
    """Retry a read-only observation once after a document/context race."""
    retried = False
    async with asyncio.timeout(1 if report.timed_out else _CAPTURE_SECONDS):
        while True:
            try:
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
                    raise StaleElement("Document changed during capture; observe again")
                return content, document_id
            except (BrowserError, CDPCommandError) as error:
                if retried or report.timed_out or not _capture_race(error):
                    raise
                retried = True
                tab.layout_changed()


def _capture_race(error: BrowserError | CDPCommandError) -> bool:
    if isinstance(error, StaleElement):
        return True
    cause = error.__cause__ if error.__cause__ is not None else error
    return isinstance(cause, CDPCommandError) and any(
        message in cause.message.lower()
        for message in (
            "cannot find context",
            "execution context was destroyed",
            "cannot find default execution context",
            "no frame with given id",
            "frame was detached",
            "inspected target navigated",
            "no node with given id",
            "could not find node with given id",
        )
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
        text=semantic_text(page.content)
        if page.content is not None
        else ((page.text,) if page.text else ()),
        scroll_y=page.scroll_y,
        elements=tuple(
            ElementFingerprint(
                role=element.role,
                name=element.name,
                in_viewport=element.in_viewport,
                value=element.value,
                description=element.description,
                options=element.options,
                multiple=element.multiple,
                scroll=element.scroll,
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
        cookie_banners=page.cookie_banners,
    )
    return fingerprint.digest()
