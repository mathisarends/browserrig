from typing import Literal

from harnessed.tracing import record, traced
from pydantic import Field

from browserrig.browser import Tab
from browserrig.core import Options, ReadinessPhase
from browserrig.observation import (
    CaptureRequest,
    PageCapture,
    Snapshot,
)

from .extraction import extract
from .handle import DomReferences
from .outline import outline
from .rendering import render

type PageProse = Literal["inline", "sparse", "off"]


class DomModel(Options):
    """Read the viewport plus a vertical context buffer; only real visibility permits input.

    Observations always list controls with their labels; the fields below add page
    prose, headings and landmarks. Dialogs and cookie banners stay grouped.
    """

    max_elements: int | None = Field(default=None, ge=1, le=50000)
    # INLINE interleaves visible prose with controls; SPARSE adds it only when the
    # viewport shows fewer than five named controls; OFF omits it.
    prose: PageProse = "inline"
    # Text budget for INLINE and SPARSE.
    max_text_chars: int = Field(default=3000, ge=1, le=100000)
    # Heading lines such as `## Pricing`.
    headings: bool = True
    # Page regions such as [MAIN] or [NAVIGATION] that group their controls.
    landmarks: bool = True
    viewport_expansion: int = Field(default=1000, ge=0, le=10000)

    @traced
    async def collect(self, tab: Tab, request: CaptureRequest) -> PageCapture:
        report = request.report
        # Comparison probes after actions need controls, not prose.
        text = "off" if report.phase == ReadinessPhase.ACTION else self.prose
        record(
            screenshots=request.screenshots,
            page_prose=text,
            headings=self.headings,
            landmarks=self.landmarks,
        )
        frames = await tab.frames()
        extracted = await extract(
            frames,
            max_elements=self.max_elements,
            max_text=self.max_text_chars if text == "inline" else 0,
            sparse_text=self.max_text_chars if text == "sparse" else 0,
            viewport_expansion=self.viewport_expansion,
            # Comparison probes match controls by identity, not by their names.
            names=report.phase != ReadinessPhase.ACTION,
        )
        page = outline(extracted, headings=self.headings, landmarks=self.landmarks)
        limitations = (*tab.frame_limitations, *page.limitations)
        return PageCapture(page.page(limitations), DomReferences())

    def render(self, snapshot: Snapshot) -> str:
        return render(snapshot)
