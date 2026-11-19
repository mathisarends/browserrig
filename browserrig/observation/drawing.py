from __future__ import annotations

import base64
import math
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import ClassVar, Protocol

from harnessed.tracing import traced
from PIL import Image, ImageDraw

from browserrig.core import Bounds

from .models import Snapshot


class ImageAnnotator(Protocol):
    """Draw on an observation's screenshot before the agent sees it.

    Annotators draw in ascending `layer` order, so higher layers stay on top.
    """

    layer: ClassVar[int]

    def draw(  # pylint: disable=unused-argument
        self, canvas: ImageDraw.ImageDraw, snapshot: Snapshot, view: ImageView
    ) -> None:
        """Draw on `canvas`, mapping viewport CSS pixels through `view`."""


@dataclass(frozen=True, slots=True)
class ImageView:
    """The viewport `area` an image shows, at `scale` image pixels per CSS pixel."""

    area: Bounds
    scale: float
    width: int
    height: int

    def project(self, bounds: Bounds) -> Bounds | None:
        """Map viewport `bounds` to image pixels; None when they are not shown."""
        shown = bounds.intersect(self.area)
        if shown.width <= 0 or shown.height <= 0:
            return None
        return Bounds(
            x=(shown.x - self.area.x) * self.scale,
            y=(shown.y - self.area.y) * self.scale,
            width=shown.width * self.scale,
            height=shown.height * self.scale,
        )


@traced
def annotate(
    image: str,
    snapshot: Snapshot,
    annotators: Sequence[ImageAnnotator],
    area: Bounds,
    *,
    scale: float = 1,
) -> str:
    """Draw annotations without inserting an overlay into the page.

    `area` is the viewport region the image shows; each image pixel is 1/`scale` CSS pixels.
    """
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        # Keep image pixels an exact multiple of viewport CSS pixels, including on HiDPI.
        canvas = source.convert("RGB").resize(
            (round(area.width * scale), round(area.height * scale)),
            Image.Resampling.LANCZOS,
        )
    draw = ImageDraw.Draw(canvas)
    view = ImageView(area, scale, canvas.width, canvas.height)
    for annotator in sorted(annotators, key=lambda annotator: annotator.layer):
        annotator.draw(draw, snapshot, view)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


@traced
def blackout(
    image: str, regions: tuple[Bounds, ...], area: Bounds, *, scale: float = 1
) -> str:
    """Paint viewport `regions` solid black in an image of `area`, e.g. fields with secrets."""
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for region in regions:
        shown = region.intersect(area)
        if shown.width <= 0 or shown.height <= 0:
            continue
        # Round outward so no anti-aliased edge of a glyph survives.
        left, top = (
            math.floor((shown.x - area.x) * scale),
            math.floor((shown.y - area.y) * scale),
        )
        right = math.ceil((shown.x + shown.width - area.x) * scale)
        bottom = math.ceil((shown.y + shown.height - area.y) * scale)
        draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill="#000000")
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")
