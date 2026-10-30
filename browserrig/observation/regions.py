from dataclasses import dataclass
from typing import Protocol

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Geometry
from browserrig.scripts import CANVAS
from browserrig.scripts.models import CanvasArgs


class CaptureRegion(Protocol):
    async def resolve(self, tab: Tab) -> Geometry | None:
        """Return a crop, or None for the full viewport. Do not capture an image."""
        ...


@dataclass(frozen=True)
class CanvasRegion:
    selector: str = "canvas"

    async def resolve(self, tab: Tab) -> Geometry | None:
        # Downloaded document previews do not contain the application's canvas.
        if tab.url.startswith("file:"):
            return None
        result = await (await tab.main_frame()).run(
            CANVAS, CanvasArgs(selector=self.selector, loading_selector=":not(*)")
        )
        if result.geometry is None:
            raise BrowserError(result.reason or "Canvas region is unavailable")
        return result.geometry
