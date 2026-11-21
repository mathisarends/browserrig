from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs
from pydantic import Field

from browserrig.core import ActionKind, Point
from browserrig.core import browser_tool as tool
from browserrig.input import Touch
from browserrig.observation import BrowserPerception, viewport_point

from .effects import Effect
from .execution import Actions
from .execution.telemetry import record_point
from .targeting import Targeting


class TouchTools(Plugin):
    """Single-finger gestures by screenshot or viewport coordinates."""

    _actions = needs(Actions)
    _touch = needs(Touch)
    _observe = needs(BrowserPerception)

    @tool(kind=ActionKind.TAP_AT, description="Tap at a point.")
    async def tap_at(
        self, x: Annotated[float, Field(ge=0)], y: Annotated[float, Field(ge=0)]
    ) -> Effect:
        point = viewport_point(self._observe.coordinate_source(), Point(x=x, y=y))
        record_point("viewport", point)
        await self._touch.tap(point)
        return Effect("Tap dispatched.")

    @tool(kind=ActionKind.SWIPE_AT, description="Swipe a finger between two points.")
    async def swipe_at(
        self,
        start: Point,
        end: Point,
        duration_seconds: Annotated[
            float, Field(ge=0.05, le=5, description="Finger travel time in seconds.")
        ] = 0.35,
    ) -> Effect:
        source = self._observe.coordinate_source()
        first = viewport_point(source, start)
        last = viewport_point(source, end)
        record_point("viewport", first, endpoint="start")
        record_point("viewport", last, endpoint="end")
        await self._touch.swipe(first, last, duration_seconds=duration_seconds)
        return Effect("Swipe dispatched.")


class ReferenceTouchTools(Plugin):
    """Tap currently visible observed targets."""

    _actions = needs(Actions)
    _targets = needs(Targeting)
    _touch = needs(Touch)

    @tool(kind=ActionKind.TAP, description="Tap a visible, hit-tested target.")
    async def tap(
        self,
        ref: Annotated[
            str, Field(description="Target reference from the observation.")
        ],
    ) -> Effect:
        point = await self._targets.locate_visible(ref=ref)
        record_point("viewport", point)
        await self._touch.tap(point)
        return Effect("Tap dispatched.")
