import asyncio
import base64
from collections.abc import Iterable
from io import BytesIO
from typing import cast

from PIL import Image, ImageStat

from browserrig.browser.images import screenshot
from browserrig.browser.tab import Tab
from browserrig.core.geometry import Geometry
from browserrig.core.kinds import ReadinessStatus
from browserrig.core.modes import CanvasMode
from browserrig.scripts import CANVAS
from browserrig.scripts.models import CanvasArgs, CanvasProbe

from .config import ReadinessOptions
from .strategy import ReadinessStrategy


async def _locate_canvas(tab: Tab, mode: CanvasMode) -> CanvasProbe:
    return await (await tab.main_frame()).run(
        CANVAS, CanvasArgs(selector=mode.selector, loading_selector=mode.loading_selector)
    )


async def _probe_canvas(tab: Tab, mode: CanvasMode) -> tuple[Geometry | None, str]:
    state = await _locate_canvas(tab, mode)
    if not state.ready or state.geometry is None:
        return None, state.reason
    geometry = state.geometry
    encoded = await screenshot(tab, geometry)
    content = await asyncio.to_thread(_has_canvas_content, encoded, mode.min_color_fraction)
    return (
        (geometry, "")
        if content
        else (None, "canvas pixels are blank or a central loading graphic")
    )


class CanvasReadiness(ReadinessStrategy):
    """Ready once a visible canvas shows content within stable bounds.

    Confirmed geometry is cached per document, so later waits only recheck pixels
    when the bounds change.
    """

    def __init__(
        self,
        tab: Tab,
        options: ReadinessOptions,
        mode: CanvasMode,
        geometry_cache: dict[tuple[str, str], Geometry],
    ) -> None:
        super().__init__(tab, options)
        self._mode = mode
        self._cache = geometry_cache
        self.geometry = geometry_cache.get(self._key)
        self.budget = options.timeout if self.geometry is not None else options.canvas_timeout
        self._last_geometry: Geometry | None = None

    @property
    def _key(self) -> tuple[str, str]:
        return self._tab.id, self._tab.document_id

    async def check(self) -> bool:
        self.delay = max(self._options.poll_interval, 0.5)
        if self.geometry is not None:
            location = await _locate_canvas(self._tab, self._mode)
            if location.ready and location.geometry == self.geometry:
                # Recheck pixels only when capture geometry changes.
                self.delay = self._options.poll_interval
                return True
            self.geometry = None
            self._cache.pop(self._key, None)
        candidate, self.reason = await _probe_canvas(self._tab, self._mode)
        if candidate is not None and candidate == self._last_geometry:
            self.geometry = candidate
            self._cache[self._key] = candidate
            return True
        self._last_geometry = candidate
        self.reason = self.reason or "canvas geometry is not stable yet"
        return False

    def timeout_status(self) -> ReadinessStatus:
        return ReadinessStatus.FAILED


def _has_canvas_content(encoded: str, min_fraction: float) -> bool:
    """Reject neutral blank images and sparse central progress graphics."""
    with Image.open(BytesIO(base64.b64decode(encoded))) as source:
        image = source.convert("RGB")
        image.thumbnail((256, 256))
        pixels = list(cast(Iterable[tuple[int, int, int]], image.get_flattened_data()))
        if not pixels:
            return False
        common = cast(
            list[tuple[int, tuple[int, int, int]]],
            image.getcolors(image.width * image.height) or [],
        )
        background = max(common, default=(0, (0, 0, 0)), key=lambda item: item[0])[1]
        changed = [
            (index % image.width, index // image.width)
            for index, pixel in enumerate(pixels)
            if max(abs(pixel[channel] - background[channel]) for channel in range(3)) > 25
        ]
        if not changed or len(changed) < len(pixels) * min_fraction:
            return False
        spread = ImageStat.Stat(image).stddev
        if max(spread) < 2:
            return False
        if len(changed) < len(pixels) * 0.06:
            xs, ys = zip(*changed, strict=True)
            if (
                min(xs) > image.width * 0.2
                and max(xs) < image.width * 0.8
                and min(ys) > image.height * 0.25
                and max(ys) < image.height * 0.75
            ):
                return False
        return True
