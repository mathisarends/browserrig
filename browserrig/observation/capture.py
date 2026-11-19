from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import uuid4

from cdpify import CDPCommandError, CDPError
from harnessed.tracing import traced

from browserrig.browser import AppState, Tab, TabInfo, dom_generation, read_generation
from browserrig.core import (
    BrowserError,
    Generation,
    Point,
    ReadinessStatus,
    Region,
    StaleElement,
)
from browserrig.readiness import ReadinessReport

from .drawing import blackout
from .frames import Frame, FrameSource, ViewportFrames
from .models import (
    PageContent,
    PageFingerprint,
    ScreenshotStatus,
    Snapshot,
    Target,
    TargetFingerprint,
)
from .references import EmptyReferences, References
from .request import CaptureRequest

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
    model: PageModel,
    report: ReadinessReport,
    *,
    frames: FrameSource | None = None,
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
        model,
        report,
        frames=frames,
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
    model: PageModel,
    report: ReadinessReport,
    *,
    frames: FrameSource | None = None,
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
    """Observe `tab`. With `previous` from the same document, unseen targets get `new`.

    `model` reads the page; `frames` captures its image, the viewport by default.
    `region` crops a screenshot to a viewport area, magnified by `zoom`.
    `cursor` is where the browser's mouse rests in `tab`.
    `redaction` hides secrets in all text and blacks out targets showing one.
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
        request = CaptureRequest(
            report, screenshots=screenshots, region=region, zoom=zoom, cursor=cursor
        )
        collected = await _collect(
            tab,
            _Sources(model, frames if frames is not None else ViewportFrames()),
            request,
            app_state=app_state,
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
    page, frame = content.page, content.frame
    image = frame.image if frame is not None else None
    screenshot_status = content.screenshot_status
    if screenshots and image is None and screenshot_status is None:
        screenshot_status = ScreenshotStatus.UNAVAILABLE
    refs = [target.ref for target in page.targets]
    for part in page.parts:
        refs.extend(part.refs())
    if len(set(refs)) != len(refs):
        raise BrowserError("Capture returned duplicate element refs")
    targets = _mark_new(page.targets, previous, tab.id, document_id)
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
        fingerprint=_fingerprint(page, document_id),
        tabs=tabs,
        text=page.text,
        targets=targets,
        parts=page.parts,
        limitations=page.limitations,
        image=image,
        screenshot_status=screenshot_status,
        geometry=frame.geometry if frame is not None else None,
        device_scale=frame.device_scale if frame is not None else None,
        cursor=cursor,
        viewport_revision=collected.viewport_revision,
        generation=collected.generation,
    )
    return CapturedObservation(snapshot, content.references)


@dataclass(frozen=True, slots=True)
class PageCapture:
    """What a page model observed, with the resolver for the refs of its targets."""

    page: PageContent
    references: References = EmptyReferences()


class PageModel(Protocol):
    """Read a page into targets and parts; the capture runner owns coherence.

    Implementations are reusable configuration. Keep per-observation state local.
    The runner retries a collection once when the document or layout changes.
    """

    async def collect(  # pylint: disable=unused-argument
        self, tab: Tab, request: CaptureRequest
    ) -> PageCapture:
        """Collect the current page and a resolver for the refs of its targets."""

    def render(self, snapshot: Snapshot) -> str:  # pylint: disable=unused-argument
        """Format a snapshot of this model as the observation text for the agent."""


@dataclass(frozen=True, slots=True)
class _Sources:
    model: PageModel
    frames: FrameSource


@dataclass(frozen=True, slots=True)
class _Content:
    page: PageContent
    references: References
    frame: Frame | None = None
    screenshot_status: ScreenshotStatus | None = None


@dataclass(frozen=True, slots=True)
class _Collected:
    content: _Content
    document_id: str
    viewport_revision: int
    generation: Generation


async def _collect(
    tab: Tab,
    sources: _Sources,
    request: CaptureRequest,
    *,
    app_state: AppState | None,
) -> _Collected:
    """Retry a read-only observation once if its generation changes."""
    retried = False
    report = request.report
    async with asyncio.timeout(1 if report.timed_out else _CAPTURE_SECONDS):
        while True:
            try:
                await tab.sync_document()
                generation = await read_generation(tab, app_state)
                document_id = tab.document_id
                viewport_revision = tab.viewport_revision
                content = await _gather(tab, sources, request)
                await tab.sync_document()
                if tab.document_id != document_id:
                    raise StaleElement("Document changed during capture; observe again")
                if generation != await read_generation(tab, app_state):
                    raise StaleElement(
                        "Page state or layout changed during capture; observe again"
                    )
                return _Collected(content, document_id, viewport_revision, generation)
            except (BrowserError, CDPError) as error:
                # Page models can issue raw commands through the CDP session.
                if not retried and not report.timed_out and _capture_race(error):
                    retried = True
                    tab.invalidate_frames()
                    continue
                if isinstance(error, CDPError) and not isinstance(error, TimeoutError):
                    raise BrowserError("Cannot collect page content") from error
                raise


async def _gather(tab: Tab, sources: _Sources, request: CaptureRequest) -> _Content:
    """Read the page while its frame is captured, so both show the same moment."""
    if not request.screenshots:
        collected = await sources.model.collect(tab, request)
        return _Content(collected.page, collected.references)
    shot = asyncio.create_task(sources.frames.capture(tab, request))
    try:
        collected = await sources.model.collect(tab, request)
    except BaseException:
        shot.cancel()
        await asyncio.gather(shot, return_exceptions=True)
        raise
    frame = await shot
    page = collected.page
    if frame.notes:
        page = replace(page, limitations=(*page.limitations, *frame.notes))
    return _Content(page, collected.references, frame)


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
    content: _Content, tab_id: str, tabs: tuple[TabInfo, ...]
) -> _Content:
    # Chrome's tab inventory can be newer than the cached title in a pixel capture.
    info = next((info for info in tabs if info.id == tab_id), None)
    if info is None or info.url != content.page.url:
        return content
    if not info.title or info.title == content.page.title:
        return content
    return replace(content, page=replace(content.page, title=info.title))


async def _redact(content: _Content, redaction: Redaction) -> _Content:
    """Redact page text before the snapshot and its fingerprint are built.

    Targets whose text holds a secret are blacked out in the image. Withhold the image
    when a secret also occurs in page text, a part or a target without known bounds.
    """
    page, frame = content.page, content.frame
    redacted = redaction.redact(page)
    if frame is None or frame.image is None or redacted is page:
        return replace(content, page=redacted)
    changed = tuple(
        target
        for target, clean in zip(page.targets, redacted.targets, strict=True)
        if clean is not target
    )
    unlocated = replace(page, targets=redacted.targets) != redacted or any(
        target.bounds is None for target in changed
    )
    if unlocated:
        return replace(
            content,
            page=redacted,
            frame=replace(frame, image=None),
            screenshot_status=ScreenshotStatus.WITHHELD,
        )
    image = await asyncio.to_thread(
        blackout,
        frame.image,
        tuple(target.bounds for target in changed if target.bounds is not None),
        frame.area,
        scale=frame.scale,
    )
    return replace(content, page=redacted, frame=replace(frame, image=image))


def _mark_new(
    targets: tuple[Target, ...],
    previous: Snapshot | None,
    tab_id: str,
    document_id: str,
) -> tuple[Target, ...]:
    if (
        previous is None
        or previous.tab_id != tab_id
        or previous.document_id != document_id
    ):
        return targets
    seen = previous.known_refs()
    if not seen:
        return targets
    marked = []
    for target in targets:
        new = target.ref not in seen
        marked.append(target.model_copy(update={"new": True}) if new else target)
    return tuple(marked)


def _fingerprint(page: PageContent, document_id: str) -> str:
    fingerprint = PageFingerprint(
        url=page.url,
        document_id=document_id,
        text=page.text,
        scroll_y=page.scroll_y,
        targets=tuple(
            TargetFingerprint(
                role=target.role, name=target.name, in_viewport=target.in_viewport
            )
            for target in page.targets
        ),
        parts=tuple(part.fingerprint(page.targets) for part in page.parts),
    )
    return fingerprint.digest()
