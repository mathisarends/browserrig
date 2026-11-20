from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs
from harnessed.tools import ToolError
from pydantic import Field

from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool
from browserrig.input import Input

from .effects import Effect


class WheelTools(Plugin):
    """Scroll the page or panel under the mouse using native wheel input."""

    _input = needs(Input)

    @tool(kind=ActionKind.SCROLL, description="Scroll at the current mouse position.")
    async def scroll(
        self,
        delta_y: Annotated[
            float,
            Field(
                ge=-10000, le=10000, description="CSS pixels down. Negative scrolls up."
            ),
        ] = 0,
        delta_x: Annotated[
            float,
            Field(
                ge=-10000,
                le=10000,
                description="CSS pixels right. Negative scrolls left.",
            ),
        ] = 0,
    ) -> Effect:
        if delta_y == 0 and delta_x == 0:
            raise ToolError("Provide a non-zero delta_y or delta_x")
        await self._input.mouse.scroll(delta_y=delta_y, delta_x=delta_x)
        return Effect("Wheel input dispatched. Inspect the next observation.")
