"""Page extraction from one DOMSnapshot per CDP session, without in-page DOM walks.

Every frame document is captured by `DOMSnapshot.captureSnapshot`, which already
carries layout, paint order, computed styles, form state and click listeners.
Roles, names and states are derived from that data in Python; Chrome's accessibility
tree then supplies the names of the listed controls.
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field

from cdpify import CdpSession
from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.exceptions import CDPCommandError

from browserrig.browser.tab import Frame
from browserrig.core.errors import BrowserError
from browserrig.observation.models import Canvas, Element, Heading, Modal, Offscreen
from browserrig.scripts import FOCUSED

from .accessibility import chrome_names, preferred
from .document import Document
from .elements import FrameExtraction, extract_frame
from .styles import STYLES

__all__ = ["Extraction", "extract"]

_TIMEOUT = 5
SPARSE_CONTROLS = 5


@dataclass(slots=True)
class Extraction:
    url: str
    title: str
    width: float
    height: float
    scroll_y: float
    page_height: float
    elements: tuple[Element, ...] = ()
    offscreen: tuple[Offscreen, ...] = ()
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    canvases: tuple[Canvas, ...] = ()
    text: str = ""
    limitations: tuple[str, ...] = field(default_factory=tuple)


async def extract(
    frames: tuple[Frame, ...],
    *,
    max_elements: int | None,
    max_text: int,
    sparse_text: int = 0,
) -> Extraction:
    """Extract all frames; `frames[0]` must be the main frame.

    `sparse_text` raises the visible-text limit when the viewport shows fewer than
    `SPARSE_CONTROLS` named controls, so pages that are mostly text still read as text.
    """
    main = frames[0]
    sessions = _sessions(frames)
    snapshots, focused = await asyncio.gather(
        asyncio.gather(
            *(_snapshot(cdp) for cdp in sessions.values()), return_exceptions=True
        ),
        asyncio.gather(
            *(_focused(frame) for frame in _session_roots(frames)),
            return_exceptions=True,
        ),
    )
    limitations: list[str] = []
    documents: dict[str, Document] = {}
    for (session_id, _), result in zip(sessions.items(), snapshots, strict=True):
        if isinstance(result, BaseException):
            if session_id == main.cdp.session_id:
                raise BrowserError(
                    "Page snapshot failed; try again after the next observation"
                ) from result
            continue
        wanted = {frame.id for frame in frames if frame.cdp.session_id == session_id}
        for document in result.documents:
            frame_id = result.strings[document.frame_id]
            if frame_id in wanted:
                documents[frame_id] = Document(document, result.strings)
    focus = {
        frame.cdp.session_id: value
        for frame, value in zip(_session_roots(frames), focused, strict=True)
        if isinstance(value, int)
    }
    extraction = _Assembler(frames, documents, focus, limitations).run(
        max_elements, max_text, sparse_text
    )
    names = await chrome_names(
        {frame.id: frame.cdp for frame in frames}, extraction.elements
    )
    if names:
        extraction.elements = tuple(
            element.model_copy(
                update={"name": preferred(element.name, names[element.ref])}
            )
            if element.ref in names
            else element
            for element in extraction.elements
        )
    return extraction


class _Assembler:
    """Merges per-frame results into one page in document order."""

    def __init__(
        self,
        frames: tuple[Frame, ...],
        documents: dict[str, Document],
        focus: dict[str, int],
        limitations: list[str],
    ) -> None:
        self._frames = frames
        self._documents = documents
        self._focus = focus
        self._limitations = limitations
        self._prefixes: dict[str, str] = {}
        self._results: dict[str, FrameExtraction] = {}
        self._keys: dict[str, tuple[int, ...]] = {}
        self._covered: set[str] = set()

    def run(
        self, max_elements: int | None, max_text: int, sparse_text: int
    ) -> Extraction:
        main = self._frames[0]
        document = self._documents.get(main.id)
        if document is None:
            raise BrowserError(
                "Page snapshot missed the main document; try again after the next observation"
            )
        for frame in self._frames:
            self._extract(frame, max(max_text, sparse_text))
        elements, headings, text = self._merge()
        # Nameless tiles and icons say nothing, so they do not count as controls.
        shown = sum(element.in_viewport and bool(element.name) for element in elements)
        limit = max_text if shown >= SPARSE_CONTROLS else max(max_text, sparse_text)
        if len(text) > limit:
            if limit:
                self._limitations.append(
                    f"Page text truncated to {limit} characters; extract_content reads it all"
                )
            text = text[:limit]
        elements = self._limit(elements, max_elements)
        visible = main.visible
        return Extraction(
            url=document.url,
            title=document.title,
            width=visible.width if visible is not None else 0,
            height=visible.height if visible is not None else 0,
            scroll_y=document.scroll[1],
            page_height=document.content_height,
            elements=tuple(elements),
            offscreen=tuple(
                control
                for result in self._results.values()
                for control in result.offscreen
            ),
            headings=tuple(headings),
            alerts=tuple(
                dict.fromkeys(
                    alert
                    for result in self._results.values()
                    for alert in result.alerts
                )
            ),
            modal=self._modal(),
            canvases=self._canvases(),
            text=text,
            limitations=tuple(dict.fromkeys(self._limitations)),
        )

    def _extract(self, frame: Frame, max_text: int) -> FrameExtraction | None:
        if frame.id in self._results:
            return self._results[frame.id]
        document = self._documents.get(frame.id)
        if document is None:
            self._limitations.append(
                f"Frame {frame.id} changed or could not be inspected"
            )
            return None
        key: tuple[int, ...] = ()
        section = ""
        if frame.parent is not None:
            parent = self._extract(frame.parent, max_text)
            if parent is None:
                return None
            owner = _index_of(parent.document, frame.owner_id)
            key = (
                *self._keys[frame.parent.id],
                owner if owner is not None else len(parent.document),
            )
            section = parent.section(owner) if owner is not None else ""
            if frame.parent.id in self._covered or (
                owner is not None and parent.covered(owner)
            ):
                self._covered.add(frame.id)
        result = extract_frame(
            document,
            frame_id=frame.id,
            transform=frame.transform,
            visible=frame.visible,
            ref_prefix=self._prefix(frame),
            focused=self._focus.get(frame.cdp.session_id),
            fallback_section=section,
            text_limit=max_text,
        )
        if frame.id in self._covered:
            result.elements = [
                (
                    index,
                    element.model_copy(update={"covered": True, "in_viewport": False}),
                )
                for index, element in result.elements
            ]
        self._results[frame.id] = result
        self._keys[frame.id] = key
        return result

    def _prefix(self, frame: Frame) -> str:
        session_id = frame.cdp.session_id
        if session_id == self._frames[0].cdp.session_id:
            return ""
        if session_id not in self._prefixes:
            self._prefixes[session_id] = f"f{len(self._prefixes) + 1}:"
        return self._prefixes[session_id]

    def _merge(self) -> tuple[list[Element], list[Heading], str]:
        ordered: list[tuple[tuple[int, ...], Element | Heading]] = []
        texts: list[str] = []
        for frame in self._frames:
            result = self._results.get(frame.id)
            if result is None:
                continue
            key = self._keys[frame.id]
            ordered.extend(
                ((*key, index), element) for index, element in result.elements
            )
            ordered.extend(
                ((*key, index), heading) for index, heading in result.headings
            )
            if result.text:
                texts.append(result.text)
        ordered.sort(key=lambda item: item[0])
        elements: list[Element] = []
        headings: list[Heading] = []
        for order, (_, item) in enumerate(ordered):
            if isinstance(item, Element):
                elements.append(item.model_copy(update={"order": order}))
            else:
                headings.append(item.model_copy(update={"order": order}))
        return elements, headings, "\n".join(texts)

    def _limit(
        self, elements: list[Element], max_elements: int | None
    ) -> list[Element]:
        if max_elements is None or len(elements) <= max_elements:
            return elements
        viewport = self._frames[0].visible
        middle = viewport.y + viewport.height / 2 if viewport is not None else 0

        def distance(element: Element) -> float:
            if element.in_viewport or element.bounds is None:
                return 0 if element.in_viewport else float("inf")
            return abs(element.bounds.y + element.bounds.height / 2 - middle)

        kept = {
            id(element) for element in sorted(elements, key=distance)[:max_elements]
        }
        self._limitations.append(
            f"Element list truncated to {max_elements} of {len(elements)}, nearest to the "
            "viewport first"
        )
        return [element for element in elements if id(element) in kept]

    def _canvases(self) -> tuple[Canvas, ...]:
        """Canvases of all uncovered frames, in page order."""
        ordered = [
            ((*self._keys[frame.id], index), canvas)
            for frame in self._frames
            if frame.id in self._results and frame.id not in self._covered
            for index, canvas in self._results[frame.id].canvases
        ]
        ordered.sort(key=lambda item: item[0])
        return tuple(canvas for _, canvas in ordered)

    def _modal(self) -> Modal | None:
        main = self._results.get(self._frames[0].id)
        if main is not None and main.modal is not None:
            return main.modal[1]
        candidates = [
            result.modal
            for result in self._results.values()
            if result.modal is not None
        ]
        return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _sessions(frames: tuple[Frame, ...]) -> dict[str, CdpSession]:
    sessions: dict[str, CdpSession] = {}
    for frame in frames:
        sessions.setdefault(frame.cdp.session_id, frame.cdp)
    return sessions


def _session_roots(frames: tuple[Frame, ...]) -> list[Frame]:
    roots: dict[str, Frame] = {}
    for frame in frames:
        roots.setdefault(frame.cdp.session_id, frame)
    return list(roots.values())


async def _snapshot(cdp: CdpSession) -> CaptureSnapshotResult:
    async with asyncio.timeout(_TIMEOUT):
        return await cdp.dom_snapshot.capture_snapshot(
            computed_styles=list(STYLES), include_paint_order=True
        )


async def _focused(frame: Frame) -> int | None:
    """Backend id of the deepest focused element in this frame's session."""
    result = await frame.run(FOCUSED, by_value=False)
    object_id = result.object_id
    if object_id is None:
        return None
    try:
        described = await frame.cdp.dom.describe_node(object_id=object_id)
        return described.node.backend_node_id
    finally:
        with suppress(CDPCommandError):
            await frame.cdp.runtime.release_object(object_id=object_id)


def _index_of(document: Document, backend_id: int | None) -> int | None:
    if backend_id is None:
        return None
    try:
        return document.backend_ids.index(backend_id)
    except ValueError:
        return None
