import base64
from enum import StrEnum
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from browserrig.core.geometry import Bounds

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


def annotate(image: str, elements: tuple[Element, ...], viewport: Bounds) -> str:
    """Draw observation-local marks without inserting an overlay into the page."""
    with Image.open(BytesIO(base64.b64decode(image))) as source:
        # Keep screenshot pixels and viewport CSS coordinates identical, including on HiDPI.
        canvas = source.convert("RGB").resize(
            (round(viewport.width), round(viewport.height)), Image.Resampling.LANCZOS
        )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=14)
    labels: list[Bounds] = []
    for element in elements:
        if element.mark is None or element.bounds is None:
            continue
        bounds = element.bounds.intersect(viewport)
        if bounds.width <= 0 or bounds.height <= 0:
            continue
        color = _COLORS.get(element.role, _Color.GRAY)
        _border(draw, bounds, color)
        label = str(element.mark)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        width, height = right - left + 8, bottom - top + 4
        x = min(max(0, bounds.x), max(0, canvas.width - width))
        y = max(0, bounds.y - height - 2)
        for _ in range(8):
            area = Bounds(x=x, y=y, width=width, height=height)
            if not any(
                area.intersect(other).width * area.intersect(other).height for other in labels
            ):
                break
            y = min(y + height + 2, max(0, canvas.height - height))
        labels.append(Bounds(x=x, y=y, width=width, height=height))
        draw.rectangle((x, y, x + width, y + height), fill=_Color.DARK, outline=color)
        draw.text((x + 4 - left, y + 2 - top), label, font=font, fill=_Color.WHITE)
    output = BytesIO()
    canvas.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _border(draw: ImageDraw.ImageDraw, bounds: Bounds, color: _Color) -> None:
    x, y, width, height = bounds.x, bounds.y, bounds.width, bounds.height
    for offset in range(0, round(width), 10):
        for edge in (y, y + height):
            draw.line((x + offset, edge, x + min(offset + 4, width), edge), fill=color, width=2)
    for offset in range(0, round(height), 10):
        for edge in (x, x + width):
            draw.line((edge, y + offset, edge, y + min(offset + 4, height)), fill=color, width=2)
