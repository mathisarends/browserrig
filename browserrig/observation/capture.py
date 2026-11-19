from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import ClassVar, Protocol
from uuid import uuid4

from cdpify import CDPCommandError, CDPError
from harnessed.tracing import traced

from browserrig.browser import AppState, Tab, TabInfo, dom_generation, read_generation
from browserrig.core import (
    Bounds,
    BrowserError,
    Generation,
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
    ScreenshotStatus,
    Snapshot,
)
from .references import EmptyReferences, References

# Both attempts share this budget; an exhausted readiness wait gets only one second.
_CAPTURE_SECONDS = 10


class Redaction(Protocol):
    """Hides known secret values, e.g. the Secrets plugin."""

    def redact[T](self, value: T) -> T:
        """Return a value of the same type with known secret text concealed."""


@dataclass(frozen=True, slots=True)
class CapturedObservation:
    """Serializable observed data paired with its per-observation reference resolver."""

    snapshot: Snapshot
    references: References

    def with_screenshot_status(self, status: ScreenshotStatus) -> CapturedObservation:
        snapshot = self.snapshot.model_copy(update={"screenshot_status": status})
        return replace(self, snapshot=snapshot)


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
    app_state: AppState | None = None,
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
        app_state=app_state,
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
    prefer_tab_title: bool = False,
    app_state: AppState | None = None,
) -> CapturedObservation:
    """Observe `tab`. With `previous` from the same document, unseen elements get `new`.

    `region` crops a screenshot to a viewport area, magnified by `zoom`.
    `cursor` is where the browser's mouse rests in `tab`; screenshots mark it.
    `redaction` hides secrets in all text and blacks out elements showing one.
    """
    snapshot_id = uuid4().hex
    dialog = tab.dialog
    if dialog is not None or report.status == ReadinessStatus.BLOCKED:
        detail = (
            f"Open {dialog.kind} dialog: {dialog.message}" if dialog else report.reason
        )
        generation = (
            dom_generation(tab) if dialog else await read_generation(tab, app_state)
        )
        if redaction is not None:
            detail = redaction.redact(detail)
        snapshot = Snapshot(
            id=snapshot_id,
            tab_id=tab.id,
            document_id=tab.document_id,
            url=tab.url,
            title=tab.title,
            readiness=ReadinessStatus.BLOCKED,
            readiness_reason=detail,
            width=0,
            height=0,
            scroll_y=0,
            fingerprint="dialog" if dialog else "blocked",
            viewport_revision=tab.viewport_revision,
            generation=generation,
            tabs=tabs,
            text=detail,
            cursor=cursor,
        )
        return CapturedObservation(snapshot, EmptyReferences())
    try:
        collected = await _collect(
            tab,
            strategy,
            report,
            app_state=app_state,
            screenshots=screenshots,
            region=region,
            zoom=zoom,
            cursor=cursor,
        )
    except (BrowserError, TimeoutError) as error:
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
            viewport_revision=tab.viewport_revision,
            generation=dom_generation(tab),
            tabs=tabs,
            text="The page is still loading. Observe again before using page controls.",
        )
        return CapturedObservation(snapshot, EmptyReferences())
    content, document_id = collected.content, collected.document_id
    if prefer_tab_title:
        content = _use_tab_title(content, tab.id, tabs)
    if redaction is not None:
        content = await _redact(content, redaction)
    page, image = content.page, content.image
    screenshot_status = content.screenshot_status
    if screenshots and image is None and screenshot_status is None:
        screenshot_status = ScreenshotStatus.UNAVAILABLE
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
        screenshot_status=screenshot_status,
        geometry=content.geometry,
        device_scale=content.device_scale,
        cursor=cursor,
        viewport_revision=collected.viewport_revision,
        generation=collected.generation,
    )
    references = (
        content.references if content.references is not None else EmptyReferences()
    )
    return CapturedObservation(snapshot, references)


@dataclass(frozen=True, slots=True)
class CaptureContent:
    """`area` is the viewport region `image` shows, at `scale` image pixels per CSS pixel.

    `fingerprint=None` uses the runner's semantic PageContent fingerprint.
    Set `screenshot_status` when reporting why an image was withheld.
    """

    page: PageContent
    image: str | None = None
    geometry: Geometry | None = None
    area: Bounds | None = None
    scale: float = 1
    fingerprint: str | None = None
    references: References | None = None
    screenshot_status: ScreenshotStatus | None = None
    device_scale: float | None = None


class CaptureStrategy(Protocol):
    """Collect content; the shared capture runner owns dialogs and document coherence.

    Implementations are reusable configuration. Keep per-observation state local.
    Supply CaptureContent.references when targets exist. The default resolves no refs.
    Set supports_dom_refs = True when the resolver returns DomElementHandle for
    the strategy's DOM refs. This enables model tools that require DOM refs.
    """

    supports_dom_refs: ClassVar[bool] = False

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
        """Collect current page data and requested image/region with its resolver."""


@dataclass(frozen=True, slots=True)
class _Collected:
    content: CaptureContent
    document_id: str
    viewport_revision: int
    generation: Generation


async def _collect(
    tab: Tab,
    strategy: CaptureStrategy,
    report: ReadinessReport,
    *,
    app_state: AppState | None,
    screenshots: bool,
    region: Region | None,
    zoom: float,
    cursor: Point | None,
) -> _Collected:
    """Retry a read-only observation once if its generation changes."""
    retried = False
    async with asyncio.timeout(1 if report.timed_out else _CAPTURE_SECONDS):
        while True:
            try:
                await tab.sync_document()
                generation = await read_generation(tab, app_state)
                document_id = tab.document_id
                viewport_revision = tab.viewport_revision
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
                if generation != await read_generation(tab, app_state):
                    raise StaleElement(
                        "Page state or layout changed during capture; observe again"
                    )
                return _Collected(content, document_id, viewport_revision, generation)
            except (BrowserError, CDPError) as error:
                # Capture strategies can issue raw commands through the CDP session.
                if not retried and not report.timed_out and _capture_race(error):
                    retried = True
                    tab.invalidate_frames()
                    continue
                if isinstance(error, CDPError) and not isinstance(error, TimeoutError):
                    raise BrowserError("Cannot collect page content") from error
                raise


def _capture_race(error: BrowserError | CDPError) -> bool:
    if isinstance(error, StaleElement):
        return True
    cause = error.__cause__ if isinstance(error, BrowserError) else error
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


def _use_tab_title(
    content: CaptureContent, tab_id: str, tabs: tuple[TabInfo, ...]
) -> CaptureContent:
    # Chrome's tab inventory can be newer than the cached title in a pixel capture.
    info = next((info for info in tabs if info.id == tab_id), None)
    if info is None or info.url != content.page.url:
        return content
    if not info.title or info.title == content.page.title:
        return content
    return replace(content, page=replace(content.page, title=info.title))


async def _redact(content: CaptureContent, redaction: Redaction) -> CaptureContent:
    """Redact page text before the snapshot and its fingerprint are built.

    Elements whose text holds a secret are blacked out in the image. Withhold the image
    when a secret also occurs in page text or in an element without known bounds.
    """
    page, image = content.page, content.image
    redacted = redaction.redact(page)
    if image is None or redacted is page:
        return replace(content, page=redacted)
    changed = tuple(
        element
        for element, clean in zip(page.elements, redacted.elements, strict=True)
        if clean is not element
    )
    unlocated = replace(page, elements=redacted.elements) != redacted or any(
        element.bounds is None for element in changed
    )
    if content.area is None or unlocated:
        return replace(
            content,
            page=redacted,
            image=None,
            screenshot_status=ScreenshotStatus.WITHHELD,
        )
    image = await asyncio.to_thread(
        blackout,
        image,
        tuple(element.bounds for element in changed if element.bounds is not None),
        content.area,
        scale=content.scale,
    )
    return replace(content, page=redacted, image=image)


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
    marked = []
    for element in elements:
        if element.ref not in seen:
            element = element.model_copy(update={"new": True})
        marked.append(element)
    return tuple(marked)


def _fingerprint(page: PageContent, document_id: str) -> str:
    if page.content is not None:
        text = semantic_text(page.content)
    elif page.text:
        text = (page.text,)
    else:
        text = ()
    fingerprint = PageFingerprint(
        url=page.url,
        document_id=document_id,
        text=text,
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
