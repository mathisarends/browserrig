import asyncio
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import assert_never
from uuid import uuid4

from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.images import screenshot
from browserrig.browser.tab import Frame, Tab
from browserrig.core.errors import BrowserError
from browserrig.core.kinds import ReadinessStatus
from browserrig.core.modes import CanvasMode, DomMode, ObservationMode
from browserrig.readiness.models import ReadinessReport
from browserrig.scripts import PAGE_FACTS, SNAPSHOT
from browserrig.scripts.models import DOMExtraction, SnapshotArgs

from .dom import seed_frame
from .marks import annotate
from .models import (
    Element,
    ElementFingerprint,
    PageFingerprint,
    Snapshot,
)


@dataclass(frozen=True, slots=True)
class _Content:
    text: tuple[str, ...] = ()
    elements: tuple[Element, ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = None
    image_digest: str | None = None


class _CaptureStrategy(ABC):
    """How one observation mode extracts page content.

    `capture` owns the shared flow: dialogs, page facts, document changes,
    fingerprint and snapshot. A strategy only collects the mode-specific content.
    """

    @abstractmethod
    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> _Content: ...


class _DomCapture(_CaptureStrategy):
    def __init__(self, mode: DomMode) -> None:
        self._mode = mode
        self._metadata: dict[str, CaptureSnapshotResult | None] = {}

    async def _extract(
        self,
        frame: Frame,
        snapshot_id: str,
        max_elements: int | None,
        max_text: int,
        limitations: list[str],
    ) -> DOMExtraction:
        await seed_frame(frame, self._metadata, limitations)
        return await frame.run(
            SNAPSHOT,
            SnapshotArgs(
                token=snapshot_id,
                max_elements=max_elements,
                max_text=max_text,
                clip=frame.local_clip,
            ),
        )

    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> _Content:
        elements: list[Element] = []
        text: list[str] = []
        frames = await browser.frames(tab)
        limitations = list(tab.frame_limitations)
        for frame in frames:
            try:
                state = await self._extract(
                    frame,
                    snapshot_id,
                    None
                    if self._mode.max_elements is None
                    else max(0, self._mode.max_elements - len(elements)),
                    max(0, self._mode.max_text_chars - sum(len(part) for part in text) - len(text)),
                    limitations,
                )
                if state.truncated:
                    limitations.append(
                        "DOM extraction was truncated by the configured content limits"
                    )
                points = tuple(frame.projection.point(item.x, item.y) for item in state.elements)
                visible = await frame.visible_points(points) if points else ()
                if state.text:
                    text.append(state.text)
                included_elements = (
                    item
                    for item, included in zip(state.elements, visible, strict=True)
                    if included or not item.in_viewport
                )
                for item in included_elements:
                    bounds = frame.projection.box(item.bounds)
                    bounds = (
                        bounds.intersect(frame.projection.clip)
                        if item.in_viewport and frame.projection.clip is not None
                        else bounds
                    )
                    elements.append(
                        Element(
                            ref=f"{snapshot_id[:8]}:{len(elements)}",
                            in_viewport=item.in_viewport,
                            mark=len(elements)
                            if self._mode.screenshots and self._mode.marks and item.in_viewport
                            else None,
                            frame_id=frame.id,
                            index=item.index,
                            role=item.role,
                            name=item.name,
                            tag=item.tag,
                            input_type=item.input_type,
                            value=item.value,
                            disabled=item.disabled,
                            checked=item.checked,
                            draggable=item.draggable,
                            options=item.options,
                            bounds=bounds,
                        )
                    )
            except (CDPCommandError, BrowserError, TimeoutError):
                if frame.parent is None:
                    raise
                limitations.append(f"Frame {frame.id} changed or could not be inspected")
        image = None
        if self._mode.screenshots:
            viewport = frames[0].projection.clip
            assert viewport is not None
            image = await asyncio.to_thread(
                annotate, await screenshot(tab), tuple(elements), viewport
            )
        return _Content(
            text=tuple(text),
            elements=tuple(elements),
            limitations=tuple(dict.fromkeys(limitations)),
            image=image,
        )


class _CanvasCapture(_CaptureStrategy):
    def __init__(self, mode: CanvasMode) -> None:
        self._mode = mode

    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> _Content:
        image = await screenshot(tab, report.geometry)
        return _Content(image=image, image_digest=hashlib.sha256(image.encode()).hexdigest())


def _capture_strategy(mode: ObservationMode) -> _CaptureStrategy:
    match mode:
        case DomMode():
            return _DomCapture(mode)
        case CanvasMode():
            return _CanvasCapture(mode)
        case _:
            assert_never(mode)


async def capture(
    browser: Browser, tab: Tab, mode: ObservationMode, report: ReadinessReport
) -> Snapshot:
    snapshot_id = uuid4().hex
    if tab.dialog:
        return Snapshot(
            id=snapshot_id,
            tab_id=tab.id,
            document_id=tab.document_id,
            url=tab.url,
            title=tab.title,
            mode=mode.kind,
            readiness=ReadinessStatus.BLOCKED,
            width=0,
            height=0,
            scroll_y=0,
            fingerprint="dialog",
            text=f"Open {tab.dialog[0]} dialog: {tab.dialog[1]}",
        )
    await tab.sync_document()
    main = await tab.main_frame()
    document_id = tab.document_id
    facts = await main.run(PAGE_FACTS)
    content = await _capture_strategy(mode).collect(browser, tab, snapshot_id, report)
    await tab.sync_document()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during capture; observe again before acting")
    fingerprint = PageFingerprint(
        url=facts.url,
        document_id=document_id,
        text=content.text,
        scroll_y=facts.scroll_y,
        elements=tuple(
            ElementFingerprint(
                role=e.role,
                name=e.name,
                in_viewport=e.in_viewport,
                value=e.value,
                disabled=e.disabled,
                checked=e.checked,
            )
            for e in content.elements
        ),
        image_digest=content.image_digest,
    ).digest()
    return Snapshot(
        id=snapshot_id,
        tab_id=tab.id,
        document_id=document_id,
        url=facts.url,
        title=facts.title,
        width=facts.width,
        height=facts.height,
        scroll_y=facts.scroll_y,
        mode=mode.kind,
        readiness=report.status,
        fingerprint=fingerprint,
        text="\n".join(content.text),
        elements=content.elements,
        limitations=content.limitations,
        image=content.image,
        geometry=report.geometry,
    )
