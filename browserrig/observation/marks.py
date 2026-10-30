import base64
import math
from enum import StrEnum
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from browserrig.core.geometry import Bounds, Point

from .models import Element


class _Color(StrEnum):
    BLUE = "#3b82f6"
    GREEN = "#22c55e"
    PURPLE = "#a855f7"
    ORANGE = "#f97316"
    PINK = "#ec4899"
    TEAL = "#14b8a6"
    GRAY = "#6b7280"
    DARK = "#1e1e1e"
    WHITE = "#ffffff"
    CURSOR = "#ef4444"


_COLORS = {
    "link": _Color.BLUE,
    "button": _Color.GREEN,
    "textbox": _Color.PURPLE,
    "searchbox": _Color.PURPLE,
    "combobox": _Color.ORANGE,
    "checkbox": _Color.PINK,
    "radio": _Color.PINK,
    "switch": _Color.PINK,
    "tab": _Color.TEAL,
}


def annotate(
    image: str,
    elements: tuple[Element, ...],
    area: Bounds,
    scale: float = 1,
    *,
    cursor: Point | None = None,
) -> str:
    """Draw element refs and the cursor without inserting an overlay into the page.

    `area` is the viewport region the image shows; each image pixel is 1/`scale` CSS pixels.
    """
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        # Keep image pixels an exact multiple of viewport CSS pixels, including on HiDPI.
        canvas = source.convert("RGB").resize(
            (round(area.width * scale), round(area.height * scale)), Image.Resampling.LANCZOS
        )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=14)
    labels: list[Bounds] = []
    for element in elements:
        if not element.in_viewport or element.bounds is None:
            continue
        shown = element.bounds.intersect(area)
        if shown.width <= 0 or shown.height <= 0:
            continue
        bounds = Bounds(
            x=(shown.x - area.x) * scale,
            y=(shown.y - area.y) * scale,
            width=shown.width * scale,
            height=shown.height * scale,
        )
        color = _COLORS.get(element.role, _Color.GRAY)
        _border(draw, bounds, color)
        label = element.ref
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        width, height = right - left + 8, bottom - top + 4
        x = min(max(0, bounds.x), max(0, canvas.width - width))
        y = max(0, bounds.y - height - 2)
        for _ in range(8):
            label_area = Bounds(x=x, y=y, width=width, height=height)
            if not any(
                label_area.intersect(other).width * label_area.intersect(other).height
                for other in labels
            ):
                break
            y = min(y + height + 2, max(0, canvas.height - height))
        labels.append(Bounds(x=x, y=y, width=width, height=height))
        draw.rectangle((x, y, x + width, y + height), fill=_Color.DARK, outline=color)
        draw.text((x + 4 - left, y + 2 - top), label, font=font, fill=_Color.WHITE)
    if cursor is not None and area.contains(cursor.x, cursor.y):
        _cursor(draw, cursor, area, scale)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def blackout(image: str, regions: tuple[Bounds, ...], area: Bounds, scale: float = 1) -> str:
    """Paint viewport `regions` solid black in an image of `area`, e.g. fields with secrets."""
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for region in regions:
        shown = region.intersect(area)
        if shown.width <= 0 or shown.height <= 0:
            continue
        # Round outward so no anti-aliased edge of a glyph survives.
        left, top = math.floor((shown.x - area.x) * scale), math.floor((shown.y - area.y) * scale)
        right = math.ceil((shown.x + shown.width - area.x) * scale)
        bottom = math.ceil((shown.y + shown.height - area.y) * scale)
        draw.rectangle((left - 2, top - 2, right + 2, bottom + 2), fill="#000000")
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _cursor(draw: ImageDraw.ImageDraw, cursor: Point, area: Bounds, scale: float) -> None:
    # The arrow's tip is the exact input coordinate, including in zoomed crops.
    x, y = (cursor.x - area.x) * scale, (cursor.y - area.y) * scale
    size = 1.3 * scale
    points = [
        (x + dx * size, y + dy * size)
        for dx, dy in ((0, 0), (0, 20), (5, 16), (9, 25), (13, 23), (9, 14), (16, 14))
    ]
    draw.line(points + points[:1], fill=_Color.WHITE, width=max(1, round(4 * size)), joint="curve")
    draw.polygon(points, fill=_Color.CURSOR, outline=_Color.DARK, width=max(1, round(size)))


def _border(draw: ImageDraw.ImageDraw, bounds: Bounds, color: _Color) -> None:
    x, y, width, height = bounds.x, bounds.y, bounds.width, bounds.height
    for offset in range(0, round(width), 10):
        for edge in (y, y + height):
            draw.line((x + offset, edge, x + min(offset + 4, width), edge), fill=color, width=2)
    for offset in range(0, round(height), 10):
        for edge in (x, x + width):
            draw.line((edge, y + offset, edge, y + min(offset + 4, height)), fill=color, width=2)
