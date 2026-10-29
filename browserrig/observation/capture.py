import hashlib
from importlib.resources import files
from uuid import uuid4

from cdpify.exceptions import CDPCommandError

from browserrig.browser.base import Browser
from browserrig.browser.errors import BrowserError
from browserrig.browser.images import screenshot
from browserrig.browser.tab import Tab
from browserrig.readiness.models import ReadinessReport

from .config import FigmaMode, ObservationMode
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
            readiness="blocked",
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
    elements: list[Element] = []
    text: list[str] = []
    limitations: list[str] = []
    frames = () if isinstance(mode, FigmaMode) else await browser.frames(tab)
    for frame in frames:
        assert not isinstance(mode, FigmaMode)
        try:
            raw_state = await frame.call(
                SNAPSHOT_SCRIPT,
                {
                    "token": snapshot_id,
                    "maxElements": max(0, mode.max_elements - len(elements)),
                    "maxText": max(0, mode.max_text_chars - sum(len(part) for part in text)),
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
    image = await screenshot(tab, report.geometry) if mode.screenshots else None
    await tab.main_frame()
    if tab.document_id != document_id:
        raise BrowserError("Document changed during capture; observe again before acting")
    fingerprint = PageFingerprint(
        url=facts.url,
        document_id=document_id,
        text=tuple(text),
        scroll_y=facts.scroll_y,
        elements=tuple(
            ElementFingerprint(role=e.role, name=e.name, value=e.value, disabled=e.disabled)
            for e in elements
        ),
        image_digest=hashlib.sha256(image.encode()).hexdigest()
        if isinstance(mode, FigmaMode) and image
        else None,
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
        text="\n".join(text),
        elements=tuple(elements),
        limitations=tuple(limitations),
        image=image,
        geometry=report.geometry,
    )
