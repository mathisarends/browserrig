import asyncio

from cdpify import CDPCommandError
from harnessed.tracing import record, traced
from pydantic import Field

from browserrig.browser import Tab, screenshot
from browserrig.core import (
    Bounds,
    BrowserError,
    Options,
    Point,
    ReadinessPhase,
    Region,
)
from browserrig.readiness import ReadinessReport

from .capture import CaptureContent
from .extraction import extract
from .handle import DomReferences
from .marks import annotate
from .models import PageContent

_MAX_REGION_SIDE = 2000
_SCREENSHOT_SECONDS = 2


class DomCapture(Options):
    """Observe the viewport plus a vertical context buffer; only real visibility permits input."""

    max_elements: int | None = Field(default=None, ge=1, le=50000)
    max_text_chars: int = Field(default=3000, ge=0, le=100000)
    viewport_expansion: int = Field(default=1000, ge=0, le=10000)
    # Show visible text on pages with fewer than five named controls.
    sparse_text_chars: int = Field(default=1500, ge=0, le=100000)
    marks: bool = True
    cursor: bool = False

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
        record(screenshots=screenshots)
        frames = await tab.frames()
        extraction = extract(
            frames,
            max_elements=self.max_elements,
            max_text=0
            if report.phase == ReadinessPhase.ACTION
            else self.max_text_chars,
            sparse_text=0
            if report.phase == ReadinessPhase.ACTION
            else self.sparse_text_chars,
            viewport_expansion=self.viewport_expansion,
            # Comparison probes match controls by identity, not by their names.
            names=report.phase != ReadinessPhase.ACTION,
        )
        if not screenshots:
            return CaptureContent(
                page=_limited(await extraction, tab), references=DomReferences()
            )
        viewport = frames[0].visible
        assert viewport is not None
        geometry = None
        notes: tuple[str, ...] = ()
        if region is not None:
            geometry = region.capture(viewport, zoom, _MAX_REGION_SIDE)
            if geometry is None:
                notes = (
                    "Screenshot region is outside the viewport; showing the full viewport",
                )
        if geometry is None:
            area, scale = (
                Bounds(x=0, y=0, width=viewport.width, height=viewport.height),
                1.0,
            )
        else:
            area = Bounds(
                x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height
            )
            scale = geometry.scale
        # The screenshot does not depend on the extraction; only its marks do.
        shot = asyncio.create_task(screenshot(tab, geometry))
        try:
            page = _limited(await extraction, tab)
        except BaseException:
            shot.cancel()
            await asyncio.gather(shot, return_exceptions=True)
            raise
        page.limitations = (*page.limitations, *notes)
        try:
            async with asyncio.timeout(_SCREENSHOT_SECONDS):
                pixels = await shot
        except (BrowserError, CDPCommandError, TimeoutError):
            page.limitations = (
                *page.limitations,
                "Screenshot unavailable; DOM observation retained",
            )
            return CaptureContent(page=page, references=DomReferences())
        image = await asyncio.to_thread(
            annotate,
            pixels,
            page.elements if self.marks else (),
            area,
            scale,
            cursor=cursor if self.cursor else None,
        )
        return CaptureContent(
            page=page,
            image=image,
            geometry=geometry,
            area=area,
            scale=scale,
            references=DomReferences(),
        )


def _limited(page: PageContent, tab: Tab) -> PageContent:
    page.limitations = tuple(dict.fromkeys((*tab.frame_limitations, *page.limitations)))
    return page
