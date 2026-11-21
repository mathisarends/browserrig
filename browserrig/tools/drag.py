import asyncio
from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind, Point
from browserrig.core import browser_tool as tool
from browserrig.input import Mouse
from browserrig.observation import BrowserPerception, viewport_point

from .effects import Effect
from .execution import Actions
from .execution.telemetry import record_point
from .targeting import Targeting

_REF = Field(description="Element reference from the observation.")


class PointerDragTools(Plugin):
    """Mouse drag by screenshot or viewport coordinates."""

    _actions = needs(Actions)
    _mouse = needs(Mouse)
    _observe = needs(BrowserPerception)

    @tool(
        kind=ActionKind.DRAG_AT,
        description="Drag between screenshot or viewport points.",
    )
    async def drag_at(self, start: Point, end: Point) -> Effect:
        source = self._observe.coordinate_source()
        viewport_start = viewport_point(source, start)
        viewport_end = viewport_point(source, end)
        return await _drag(self._mouse, viewport_start, viewport_end)


class ReferenceDragTools(Plugin):
    """Mouse drag between resolvable element references."""

    _actions = needs(Actions)
    _mouse = needs(Mouse)
    _targets = needs(Targeting)

    @tool(
        kind=ActionKind.DRAG,
        description=(
            "Drag between observed refs, scrolling them into view when supported. "
            "Both endpoints must fit in the viewport together."
        ),
    )
    async def drag(
        self, source_ref: Annotated[str, _REF], target_ref: Annotated[str, _REF]
    ) -> Effect:
        source = await self._targets.locate(ref=source_ref)
        target = await self._targets.locate(ref=target_ref)
        # The second reveal can move the first target. Hit-test both after scrolling.
        start, end = await asyncio.gather(
            self._targets.locate(ref=source_ref, scroll=False),
            self._targets.locate(ref=target_ref, scroll=False),
        )
        return await _drag(
            self._mouse, start, end, prepared_scroll=source.scrolled or target.scrolled
        )


async def _drag(
    mouse: Mouse, start: Point, end: Point, *, prepared_scroll: bool = False
) -> Effect:
    record_point("viewport", start, endpoint="start")
    record_point("viewport", end, endpoint="end")
    await mouse.drag(start=start, end=end)
    return Effect(
        "Drag dispatched; inspect the destination.", prepared_scroll=prepared_scroll
    )
