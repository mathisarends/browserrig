from typing import Annotated

from harnessed import Plugin, ToolResult
from harnessed.kernel import Inject, needs
from pydantic import Field

from browserrig.core import ActionKind, Region
from browserrig.core import browser_tool as tool
from browserrig.observation import BrowserPerception


def _screenshots_enabled(perception: Inject[BrowserPerception | None]) -> bool:
    return perception is not None and perception.screenshots is not None


class ScreenshotTools(Plugin):
    """Offer explicit screenshot requests independently of automatic capture."""

    _observe = needs(BrowserPerception)

    @tool(
        kind=ActionKind.SCREENSHOT,
        enabled=_screenshots_enabled,
        readonly=True,
        description="Request a screenshot for the next observation.",
    )
    async def screenshot(
        self,
        region: Annotated[
            Region | None,
            Field(
                description="Viewport area in CSS pixels; omit for the full viewport."
            ),
        ] = None,
    ) -> ToolResult:
        self._observe.request_screenshot(region=region)
        return ToolResult("Screenshot requested.")
