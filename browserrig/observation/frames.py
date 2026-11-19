from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol, override

from PIL import Image

from browserrig.browser import Tab, screenshot
from browserrig.core import Bounds, BrowserError, Geometry, Region

from .request import CaptureRequest

_MAX_REGION_SIDE = 2000
_SCREENSHOT_SECONDS = 2


class FrameSource(Protocol):
    """Capture the image of an observation, e.g. the viewport or an app's canvas."""

    async def capture(  # pylint: disable=unused-argument
        self, tab: Tab, request: CaptureRequest
    ) -> Frame:
        """Capture the requested region; an unavailable image has `image=None`."""


@dataclass(frozen=True, slots=True)
class Frame:
    """`area` is the viewport region `image` shows, at `geometry.scale` pixels per CSS pixel.

    `notes` explain how the image differs from the request.
    """

    image: str | None
    area: Bounds
    geometry: Geometry | None = None
    notes: tuple[str, ...] = ()
    device_scale: float | None = None

    @property
    def scale(self) -> float:
        return self.geometry.scale if self.geometry is not None else 1.0


class ViewportFrames(FrameSource):
    """Capture the tab's viewport in CSS pixels, independent of the device scale."""

    @override
    async def capture(self, tab: Tab, request: CaptureRequest) -> Frame:
        size = (await tab.page_layout()).viewport
        viewport = Bounds(x=0, y=0, width=size.width, height=size.height)
        return await capture_pixels(
            tab, viewport, region=request.region, zoom=request.zoom
        )


async def capture_pixels(
    tab: Tab,
    viewport: Bounds,
    *,
    region: Region | None,
    zoom: float,
) -> Frame:
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
    except (BrowserError, TimeoutError):
        return Frame(None, area, None, notes)
    scale = geometry.scale if geometry is not None else 1.0
    image, device_scale = await asyncio.to_thread(_normalize, raw, area, scale=scale)
    return Frame(image, area, geometry, notes, device_scale=device_scale)


def _normalize(image: str, area: Bounds, *, scale: float) -> tuple[str, float]:
    """Keep untouched PNGs when possible; map HiDPI captures to tool coordinates."""
    size = (round(area.width * scale), round(area.height * scale))
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        device_scale = source.width / size[0]
        if source.size == size:
            return image, device_scale
        canvas = source.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii"), device_scale
