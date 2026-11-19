from enum import StrEnum
from typing import ClassVar, override

from harnessed import Instructions, Plugin, SystemPrompt
from harnessed.kernel import PluginScope, needs
from PIL import ImageDraw, ImageFont

from browserrig.core import Bounds

from .drawing import ImageAnnotator, ImageView
from .models import Snapshot
from .plugin import BrowserPerception


class SetOfMarks(Plugin, slot="browserrig.marks"):
    """Outline screenshot targets and label them with their observation refs."""

    _perception = needs(BrowserPerception)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.add_annotator(MarksAnnotator()))

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Screenshot marks",
                text="Each marked element in a screenshot is outlined and labeled with its ref.",
            )
        )


class MarksAnnotator(ImageAnnotator):
    """Label the visible targets of any page model, below other annotations."""

    layer: ClassVar[int] = 0

    @override
    def draw(
        self, canvas: ImageDraw.ImageDraw, snapshot: Snapshot, view: ImageView
    ) -> None:
        font = ImageFont.load_default(size=14)
        labels: list[Bounds] = []
        for target in snapshot.targets:
            if not target.in_viewport or target.bounds is None:
                continue
            bounds = view.project(target.bounds)
            if bounds is None:
                continue
            color = _COLORS.get(target.role, _Color.GRAY)
            _border(canvas, bounds, color)
            label = target.ref
            left, top, right, bottom = canvas.textbbox((0, 0), label, font=font)
            width, height = right - left + 8, bottom - top + 4
            x = min(max(0, bounds.x), max(0, view.width - width))
            label_area = _place(
                labels,
                view,
                Bounds(
                    x=x, y=max(0, bounds.y - height - 2), width=width, height=height
                ),
            )
            labels.append(label_area)
            x, y = label_area.x, label_area.y
            canvas.rectangle(
                (x, y, x + width, y + height), fill=_Color.DARK, outline=color
            )
            canvas.text(
                (x + 4 - left, y + 2 - top), label, font=font, fill=_Color.WHITE
            )


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


def _place(labels: list[Bounds], view: ImageView, area: Bounds) -> Bounds:
    """Move a label down until it no longer covers an earlier one."""
    for _ in range(8):
        if not any(
            area.intersect(other).width * area.intersect(other).height
            for other in labels
        ):
            break
        y = min(area.y + area.height + 2, max(0, view.height - area.height))
        area = area.model_copy(update={"y": y})
    return area


def _border(draw: ImageDraw.ImageDraw, bounds: Bounds, color: _Color) -> None:
    x, y, width, height = bounds.x, bounds.y, bounds.width, bounds.height
    for offset in range(0, round(width), 10):
        for edge in (y, y + height):
            draw.line(
                (x + offset, edge, x + min(offset + 4, width), edge),
                fill=color,
                width=2,
            )
    for offset in range(0, round(height), 10):
        for edge in (x, x + width):
            draw.line(
                (edge, y + offset, edge, y + min(offset + 4, height)),
                fill=color,
                width=2,
            )
