import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.resources import files
from typing import assert_never
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.errors import BrowserError
from browserrig.browser.images import screenshot
from browserrig.browser.tab import Tab
from browserrig.kinds import ReadinessStatus
from browserrig.readiness.models import ReadinessReport

from .config import CanvasMode, DomMode, ObservationMode
from .models import (
    DOMExtraction,
    Element,
    ElementFingerprint,
    PageFacts,
    PageFingerprint,
    Snapshot,
)

SNAPSHOT_SCRIPT = (
    files("browserrig.observation").joinpath("scripts/snapshot.js").read_text(encoding="utf-8")
)
ELEMENT_SCRIPT = (
    files("browserrig.observation").joinpath("scripts/element.js").read_text(encoding="utf-8")
)


@dataclass(frozen=True, slots=True)
class Content:
    """What one observation mode extracted from the page."""

    text: tuple[str, ...] = ()
    elements: tuple[Element, ...] = ()
    limitations: tuple[str, ...] = ()
    image: str | None = None
    image_digest: str | None = None


class CaptureStrategy(ABC):
    """How one observation mode extracts page content.

    `capture` owns the shared flow: dialogs, page facts, document changes,
    fingerprint and snapshot. A strategy only collects the mode-specific content.
    """

    @abstractmethod
    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> Content: ...


class DomCapture(CaptureStrategy):
    """Visible text and interactive elements from every inspectable frame."""

    def __init__(self, mode: DomMode) -> None:
        self.mode = mode

    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> Content:
        elements: list[Element] = []
        text: list[str] = []
        limitations: list[str] = []
        for frame in await browser.frames(tab):
            try:
                raw_state = await frame.call(
                    SNAPSHOT_SCRIPT,
                    {
                        "token": snapshot_id,
                        "maxElements": max(0, self.mode.max_elements - len(elements)),
                        "maxText": max(
                            0, self.mode.max_text_chars - sum(len(part) for part in text)
                        ),
                    },
                )
                state = DOMExtraction.model_validate(raw_state)
                text.append(state.text)
                for item in state.elements:
                    elements.append(
                        Element(
                            ref=f"{snapshot_id[:8]}:{len(elements)}",
                            frame_id=frame.id,
                            index=item.index,
                            role=item.role,
                            name=item.name,
                            tag=item.tag,
                            input_type=item.input_type,
                            value=item.value,
                            disabled=item.disabled,
                            draggable=item.draggable,
                            options=item.options,
                        )
                    )
            except CDPCommandError:
                limitations.append(f"Frame {frame.id} changed or could not be inspected")
        image = await screenshot(tab, report.geometry) if self.mode.screenshots else None
        return Content(
            text=tuple(text),
            elements=tuple(elements),
            limitations=tuple(limitations),
            image=image,
        )


class CanvasCapture(CaptureStrategy):
    """An image of the confirmed canvas area; its pixels drive the fingerprint."""

    def __init__(self, mode: CanvasMode) -> None:
        self.mode = mode

    async def collect(
        self, browser: Browser, tab: Tab, snapshot_id: str, report: ReadinessReport
    ) -> Content:
        image = await screenshot(tab, report.geometry)
        return Content(image=image, image_digest=hashlib.sha256(image.encode()).hexdigest())


def capture_strategy(mode: ObservationMode) -> CaptureStrategy:
    match mode:
        case DomMode():
            return DomCapture(mode)
        case CanvasMode():
            return CanvasCapture(mode)
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
    main = await tab.main_frame()
    document_id = tab.document_id
    facts = PageFacts.model_validate(
        await main.evaluate(
            "({url: location.href, title: document.title, width: innerWidth, "
            "height: innerHeight, scroll_y: scrollY})"
        )
    )
    content = await capture_strategy(mode).collect(browser, tab, snapshot_id, report)
    await tab.main_frame()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during capture; observe again before acting")
    fingerprint = PageFingerprint(
        url=facts.url,
        document_id=document_id,
        text=content.text,
        scroll_y=facts.scroll_y,
        elements=tuple(
            ElementFingerprint(role=e.role, name=e.name, value=e.value, disabled=e.disabled)
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
