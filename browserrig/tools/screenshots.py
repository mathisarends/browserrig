from typing import Annotated

from harnessed import Plugin, ToolResult
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind, Region
from browserrig.core import browser_tool as tool
from browserrig.observation import BrowserPerception


class ScreenshotTools(Plugin):
    """Offer explicit screenshot requests independently of automatic capture."""

    _observe = needs(BrowserPerception)

    @tool(
        kind=ActionKind.SCREENSHOT,
        readonly=True,
        description=(
            "Request a screenshot of the active tab for visual inspection in your next iteration. "
            "The next observation includes an image and matching page state. "
            "Region limits the image to a viewport area in CSS pixels, such as a "
            "listed canvas, and zoom magnifies it to read small details; "
            "move_mouse, click_at and drag_at then take pixels of that image. "
            "This does not enable automatic screenshots for later iterations."
        ),
    )
    async def screenshot(
        self,
        region: Annotated[
            Region | None,
            Field(
                description="Viewport area in CSS pixels; omit for the full viewport."
            ),
        ] = None,
        zoom: Annotated[
            float, Field(ge=1, le=4, description="Magnification of the region image.")
        ] = 1,
    ) -> ToolResult:
        self._observe.request_screenshot(region=region, zoom=zoom)
        target = "requested region" if region is not None else "current viewport"
        return ToolResult(
            f"Screenshot requested. Your next observation will show the {target}."
        )
