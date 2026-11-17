import asyncio
import base64
from dataclasses import dataclass, replace
from io import BytesIO
from typing import override

from cdpify import CDPCommandError
from PIL import Image

from browserrig.browser import Tab, screenshot
from browserrig.core import Bounds, BrowserError, Geometry, Point, Region
from browserrig.readiness import ReadinessReport

from .capture import CaptureContent, CaptureStrategy
from .models import PageContent

_MAX_REGION_SIDE = 2000
_SCREENSHOT_SECONDS = 2


class ScreenshotCapture(CaptureStrategy):
    """Collect pixels and viewport geometry without inspecting page elements."""

    @override
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
        del report, cursor
        size = await tab.viewport_size()
        page = PageContent(
            url=tab.url,
            title=tab.title,
            width=size.width,
            height=size.height,
            scroll_y=0,
            page_height=0,
        )
        if not screenshots:
            return CaptureContent(page=page)
        viewport = Bounds(x=0, y=0, width=size.width, height=size.height)
        pixels = await capture_pixels(tab, viewport, region=region, zoom=zoom)
        return pixels.attach(CaptureContent(page=page))


@dataclass(frozen=True, slots=True)
class ScreenshotPixels:
    image: str | None
    area: Bounds
    geometry: Geometry | None
    notes: tuple[str, ...]

    def attach(self, content: CaptureContent) -> CaptureContent:
        page = replace(
            content.page, limitations=(*content.page.limitations, *self.notes)
        )
        return replace(
            content,
            page=page,
            image=self.image,
            area=self.area,
            geometry=self.geometry,
            scale=self.geometry.scale if self.geometry else 1.0,
        )


async def capture_pixels(
    tab: Tab,
    viewport: Bounds,
    *,
    region: Region | None,
    zoom: float,
) -> ScreenshotPixels:
    """Capture the viewport or its crop and normalize to the coordinate space."""
    geometry = region.capture(viewport, zoom, _MAX_REGION_SIDE) if region else None
    notes: tuple[str, ...] = ()
    if geometry is not None:
        area = Bounds(
            x=geometry.x, y=geometry.y, width=geometry.width, height=geometry.height
        )
    else:
        area = viewport
        if region is not None:
            notes = (
                "Screenshot region is outside the viewport; showing the full viewport",
            )
    try:
        async with asyncio.timeout(_SCREENSHOT_SECONDS):
            raw = await screenshot(tab, geometry)
    except (BrowserError, CDPCommandError, TimeoutError):
        return ScreenshotPixels(None, area, None, (*notes, "Screenshot unavailable"))
    scale = geometry.scale if geometry is not None else 1.0
    image = await asyncio.to_thread(_normalize, raw, area, scale=scale)
    return ScreenshotPixels(image, area, geometry, notes)


def _normalize(image: str, area: Bounds, *, scale: float) -> str:
    """Keep untouched PNGs when possible; map HiDPI captures to tool coordinates."""
    size = (round(area.width * scale), round(area.height * scale))
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        if source.size == size:
            return image
        canvas = source.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")
