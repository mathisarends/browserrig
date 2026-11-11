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
        description="Include one screenshot in the next observation.",
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
        target = "requested region" if region is not None else "current viewport"
        return ToolResult(
            f"Screenshot requested. Your next observation will show the {target}."
        )
