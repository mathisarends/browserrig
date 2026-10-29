import asyncio
import base64
from collections.abc import Iterable
from importlib.resources import files
from io import BytesIO
from typing import cast

from PIL import Image, ImageStat

from browserrig.browser.config import Options
from browserrig.browser.images import screenshot
from browserrig.browser.models import Geometry
from browserrig.browser.tab import Tab, script_call
from browserrig.observation.config import FigmaMode

SCRIPT = files("browserrig.readiness").joinpath("scripts/canvas.js").read_text(encoding="utf-8")


class FigmaProbe(Options):
    ready: bool
    geometry: Geometry | None = None
    reason: str = ""


async def locate_prototype(tab: Tab, mode: FigmaMode) -> FigmaProbe:
    return FigmaProbe.model_validate(
        await tab.evaluate(
            script_call(
                SCRIPT,
                {
                    "selector": mode.selector,
                    "loadingSelector": mode.loading_selector,
                },
            )
        )
    )


async def probe_figma(tab: Tab, mode: FigmaMode) -> tuple[Geometry | None, str]:
    state = await locate_prototype(tab, mode)
    if not state.ready or state.geometry is None:
        return None, state.reason
    geometry = state.geometry
    encoded = await screenshot(tab, geometry)
    content = await asyncio.to_thread(_has_prototype_content, encoded, mode.min_color_fraction)
    return (
        (geometry, "")
        if content
        else (None, "canvas pixels are blank or a central loading graphic")
    )


def _has_prototype_content(encoded: str, min_fraction: float) -> bool:
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
        if len(changed) < len(pixels) * min_fraction:
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
