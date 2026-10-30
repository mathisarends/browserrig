import asyncio
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import assert_never
from uuid import uuid4

from browserrig.browser.images import screenshot
from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.kinds import ReadinessStatus
from browserrig.core.modes import CanvasMode, DomMode, ObservationMode
from browserrig.readiness.models import ReadinessReport
from browserrig.scripts import PAGE_FACTS

from .extraction import Extraction, extract
from .marks import annotate
from .models import Element, ElementFingerprint, PageFingerprint, Snapshot


@dataclass(frozen=True, slots=True)
class _Content:
    page: Extraction
    image: str | None = None
    image_digest: str | None = None


class _CaptureStrategy(ABC):
    """How one observation mode extracts page content.

    `capture` owns the shared flow: dialogs, document changes, fingerprint and
    snapshot. A strategy only collects the mode-specific content.
    """

    @abstractmethod
    async def collect(self, tab: Tab, report: ReadinessReport) -> _Content: ...


class _DomCapture(_CaptureStrategy):
    def __init__(self, mode: DomMode) -> None:
        self._mode = mode

    async def collect(self, tab: Tab, report: ReadinessReport) -> _Content:
        frames = await tab.frames()
        page = await extract(
            frames, max_elements=self._mode.max_elements, max_text=self._mode.max_text_chars
        )
        page.limitations = tuple(dict.fromkeys((*tab.frame_limitations, *page.limitations)))
        image = None
        if self._mode.screenshots:
            viewport = frames[0].visible
            assert viewport is not None
            marked = page.elements if self._mode.marks else ()
            image = await asyncio.to_thread(annotate, await screenshot(tab), marked, viewport)
        return _Content(page=page, image=image)


class _CanvasCapture(_CaptureStrategy):
    def __init__(self, mode: CanvasMode) -> None:
        self._mode = mode

    async def collect(self, tab: Tab, report: ReadinessReport) -> _Content:
        facts = await (await tab.main_frame()).run(PAGE_FACTS)
        image = await screenshot(tab, report.geometry)
        page = Extraction(
            url=facts.url,
            title=facts.title,
            width=facts.width,
            height=facts.height,
            scroll_y=facts.scroll_y,
            page_height=0,
        )
        return _Content(
            page=page, image=image, image_digest=hashlib.sha256(image.encode()).hexdigest()
        )


def _capture_strategy(mode: ObservationMode) -> _CaptureStrategy:
    match mode:
        case DomMode():
            return _DomCapture(mode)
        case CanvasMode():
            return _CanvasCapture(mode)
        case _:
            assert_never(mode)


async def capture(
    tab: Tab,
    mode: ObservationMode,
    report: ReadinessReport,
    *,
    tabs: tuple[TabInfo, ...] = (),
    previous: Snapshot | None = None,
) -> Snapshot:
    """Observe `tab`. With `previous` from the same document, unseen elements get `new`."""
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
            tabs=tabs,
            text=f"Open {tab.dialog[0]} dialog: {tab.dialog[1]}",
        )
    await tab.sync_document()
    document_id = tab.document_id
    content = await _capture_strategy(mode).collect(tab, report)
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
        mode=mode.kind,
        readiness=report.status,
        fingerprint=_fingerprint(page, document_id, content.image_digest),
        tabs=tabs,
        text=page.text,
        elements=elements,
        headings=page.headings,
        alerts=page.alerts,
        modal=page.modal,
        limitations=page.limitations,
        image=content.image,
        geometry=report.geometry,
    )


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
