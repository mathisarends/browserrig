import asyncio

from harnessed.tracing import record, traced
from pydantic import Field

from browserrig.browser import Tab
from browserrig.core import (
    Options,
    Point,
    ReadinessPhase,
    Region,
)
from browserrig.readiness import ReadinessReport

from .capture import CaptureContent
from .config import PageText
from .extraction import extract
from .handle import DomReferences
from .models import PageContent
from .outline import outline
from .pixels import capture_pixels


class DomCapture(Options):
    """Observe the viewport plus a vertical context buffer; only real visibility permits input.

    Observations always list controls with their labels; the fields below add page
    prose, headings and landmarks. Dialogs and cookie banners stay grouped.
    """

    max_elements: int | None = Field(default=None, ge=1, le=50000)
    # INLINE interleaves visible prose with controls; SPARSE adds it only when the
    # viewport shows fewer than five named controls; OFF omits it.
    text: PageText = PageText.INLINE
    # Text budget for INLINE and SPARSE.
    max_text_chars: int = Field(default=3000, ge=1, le=100000)
    # Heading lines such as `## Pricing`.
    headings: bool = True
    # Page regions such as [MAIN] or [NAVIGATION] that group their controls.
    landmarks: bool = True
    viewport_expansion: int = Field(default=1000, ge=0, le=10000)

    @traced
    async def collect(
        self,
        tab: Tab,
        report: ReadinessReport,
        *,
        screenshots: bool,
        region: Region | None = None,
        zoom: float = 1,
        cursor: Point | None = None,
    ) -> CaptureContent:
        del cursor
        # Comparison probes after actions need controls, not prose.
        text = PageText.OFF if report.phase == ReadinessPhase.ACTION else self.text
        record(
            screenshots=screenshots,
            page_text=text,
            headings=self.headings,
            landmarks=self.landmarks,
        )
        frames = await tab.frames()
        extraction = extract(
            frames,
            max_elements=self.max_elements,
            max_text=self.max_text_chars if text == PageText.INLINE else 0,
            sparse_text=self.max_text_chars if text == PageText.SPARSE else 0,
            viewport_expansion=self.viewport_expansion,
            # Comparison probes match controls by identity, not by their names.
            names=report.phase != ReadinessPhase.ACTION,
        )
        if not screenshots:
            extracted = await extraction
            return CaptureContent(
                page=_limited(self._outline(extracted), tab), references=DomReferences()
            )
        viewport = frames[0].visible
        assert viewport is not None
        shot = asyncio.create_task(
            capture_pixels(tab, viewport, region=region, zoom=zoom)
        )
        try:
            extracted = await extraction
            page = _limited(self._outline(extracted), tab)
        except BaseException:
            shot.cancel()
            await asyncio.gather(shot, return_exceptions=True)
            raise
        pixels = await shot
        return pixels.attach(CaptureContent(page=page, references=DomReferences()))

    def _outline(self, page: PageContent) -> PageContent:
        return outline(page, headings=self.headings, landmarks=self.landmarks)


def _limited(page: PageContent, tab: Tab) -> PageContent:
    page.limitations = tuple(dict.fromkeys((*tab.frame_limitations, *page.limitations)))
    return page
