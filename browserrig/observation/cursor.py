from typing import ClassVar, override

from harnessed import Plugin, SystemPrompt
from harnessed.kernel import PluginScope, needs
from harnessed.prompts import Instructions
from PIL import ImageDraw

from .drawing import ImageAnnotator, ImageView
from .models import Snapshot
from .plugin import BrowserPerception

_CURSOR = "#ef4444"
_OUTLINE = "#1e1e1e"
_HALO = "#ffffff"


class CursorMarker(Plugin, slot="browserrig.cursor-marker"):
    """Draw the mouse pointer on screenshots, e.g. for canvas apps without targets."""

    _perception = needs(BrowserPerception)

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.add_annotator(CursorAnnotator()))

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Screenshot cursor",
                text="A red arrow in a screenshot marks where the mouse rests; its tip is "
                "the exact pointer position.",
            )
        )


class CursorAnnotator(ImageAnnotator):
    """Draw the pointer above all other annotations."""

    layer: ClassVar[int] = 100

    @override
    def draw(
        self, canvas: ImageDraw.ImageDraw, snapshot: Snapshot, view: ImageView
    ) -> None:
        cursor, area = snapshot.cursor, view.area
        if cursor is None or not area.contains(cursor.x, cursor.y):
            return
        # The arrow's tip is the exact input coordinate, including in zoomed crops.
        x, y = (cursor.x - area.x) * view.scale, (cursor.y - area.y) * view.scale
        size = 1.3 * view.scale
        points = [
            (x + dx * size, y + dy * size)
            for dx, dy in (
                (0, 0),
                (0, 20),
                (5, 16),
                (9, 25),
                (13, 23),
                (9, 14),
                (16, 14),
            )
        ]
        canvas.line(
            points + points[:1],
            fill=_HALO,
            width=max(1, round(4 * size)),
            joint="curve",
        )
        canvas.polygon(
            points, fill=_CURSOR, outline=_OUTLINE, width=max(1, round(size))
        )
