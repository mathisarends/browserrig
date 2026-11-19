import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from harnessed import (
    Instructions,
    Plugin,
    SystemPrompt,
    ToolError,
)
from harnessed.kernel import needs, observes
from pydantic import Field

from browserrig.browser import Browser, TabPolicy
from browserrig.core import ActionKind, BrowserError, Point
from browserrig.core import browser_tool as tool
from browserrig.input import ClickButton, ClickCount, Input
from browserrig.observation import BrowserPerception, CapturedImage, Snapshot

from .effects import Effect
from .execution import Actions
from .execution.telemetry import record_point
from .parameters import NewTab
from .targeting import Targeting

type _ClickCount = Annotated[
    ClickCount,
    Field(description="Use 2 for a native double click."),
]
_DRAG_DURATION = Field(ge=0.05, le=5, description="Drag duration in seconds.")
_REF = Field(description="Element reference from the observation.")
_X_COORDINATE = Field(ge=0, description="Horizontal position from the left edge.")
_Y_COORDINATE = Field(ge=0, description="Vertical position from the top edge.")


_INSTRUCTIONS = Instructions(
    title="Screenshot coordinates",
    text=(
        "Point in pixels from the top-left of the newest screenshot still in context; "
        "crop and scale map back to the viewport. Without an image, use viewport CSS pixels. "
        "After scrolling or other changes to the page layout or document, "
        "use a fresh screenshot before pointing."
    ),
)


class _PointerInput(Plugin):
    """Share native click dispatch and new-tab behavior across pointer tools."""

    _actions = needs(Actions)
    _browser = needs(Browser)
    _input = needs(Input)
    _tabs = observes(TabPolicy)

    def _check_click(
        self, *, count: ClickCount, button: ClickButton, new_tab: bool
    ) -> None:
        if new_tab and (count != 1 or button != "left"):
            raise ToolError("new_tab needs a single left click")
        if new_tab and self._tabs is not None:
            self._tabs.check_new_tab()

    async def _dispatch_click(
        self,
        point: Point,
        *,
        count: ClickCount,
        button: ClickButton,
        new_tab: bool,
        prepared_scroll: bool = False,
    ) -> Effect:
        mouse = self._input.mouse
        record_point("viewport", point)
        if new_tab:
            # Arrive first, so the keys are held for the click alone.
            await mouse.move_to(point)
        async with self._new_tab_keys(new_tab) as modifiers:
            await mouse.click(point, count=count, button=button, modifiers=modifiers)
        return Effect(
            _click_message(count, button, new_tab),
            prepared_scroll=prepared_scroll,
            break_chain=button == "right",
            expects_new_tab=new_tab,
        )

    @asynccontextmanager
    async def _new_tab_keys(self, new_tab: bool) -> AsyncGenerator[int]:
        """Use Chrome's foreground new-tab shortcut and show the keys to viewers."""
        if not new_tab:
            yield 0
            return
        key = await self._browser.tabs.link_modifier()
        async with self._input.keyboard.hold(key, "Shift") as modifiers:
            yield modifiers


class PointerTools(_PointerInput):
    """Mouse input by screenshot or viewport coordinates."""

    _observe = needs(BrowserPerception)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @tool(
        kind=ActionKind.MOVE_MOUSE,
        description="Move to a point without clicking.",
    )
    async def move_mouse(
        self, x: Annotated[float, _X_COORDINATE], y: Annotated[float, _Y_COORDINATE]
    ) -> Effect:
        point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
        record_point("viewport", point)
        await self._input.mouse.move_to(point)
        return Effect("Cursor moved without clicking.")

    @tool(
        kind=ActionKind.CLICK_AT,
        description="Click at screenshot or viewport coordinates.",
    )
    async def click_at(
        self,
        x: Annotated[float, _X_COORDINATE],
        y: Annotated[float, _Y_COORDINATE],
        *,
        count: _ClickCount = 1,
        button: ClickButton = "left",
        new_tab: NewTab = False,
    ) -> Effect:
        self._check_click(count=count, button=button, new_tab=new_tab)
        point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
        return await self._dispatch_click(
            point, count=count, button=button, new_tab=new_tab
        )

    @tool(
        kind=ActionKind.DRAG_AT,
        description="Drag between screenshot or viewport points.",
    )
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration_seconds: Annotated[float, _DRAG_DURATION] = 0.5,
    ) -> Effect:
        source = self._observe.coordinate_source()
        viewport_start = _image_point(source, start)
        viewport_end = _image_point(source, end)
        record_point("viewport", viewport_start, endpoint="start")
        record_point("viewport", viewport_end, endpoint="end")
        await self._input.mouse.drag(
            start=viewport_start,
            end=viewport_end,
            duration_seconds=duration_seconds,
        )
        return Effect("Drag dispatched; inspect the destination.")


class ReferencePointerTools(_PointerInput):
    """Mouse input by resolvable element references."""

    _targets = needs(Targeting)

    @tool(
        kind=ActionKind.HOVER,
        description="Hover an observed element, revealing it when needed.",
    )
    async def hover(self, ref: Annotated[str, _REF]) -> Effect:
        point = await self._targets.locate(ref=ref)
        record_point("viewport", point)
        await self._input.mouse.move_to(point)
        return Effect(
            "Cursor moved onto the ref without clicking.",
            prepared_scroll=point.scrolled,
        )

    @tool(
        kind=ActionKind.CLICK,
        chainable=True,
        description="Click an observed ref, revealing it first when needed.",
    )
    async def click(
        self,
        ref: Annotated[str, _REF],
        *,
        count: _ClickCount = 1,
        button: ClickButton = "left",
        new_tab: NewTab = False,
    ) -> Effect:
        self._check_click(count=count, button=button, new_tab=new_tab)
        point = await self._targets.locate(ref=ref)
        await self._input.mouse.move_to(point)
        if change := await self._actions.page_change(after_input=False):
            return Effect(
                f"Hover changed the page: {change} The click was not dispatched. "
                "Inspect the next observation before choosing a target.",
                prepared_scroll=point.scrolled,
                break_chain=True,
                blocked_reason=change,
            )
        # Hover may reveal an overlay or move the target; hit-test again.
        current = await self._targets.locate(ref=ref, scroll=False)
        return await self._dispatch_click(
            current,
            count=count,
            button=button,
            new_tab=new_tab,
            prepared_scroll=point.scrolled,
        )

    @tool(
        kind=ActionKind.DRAG,
        description=(
            "Drag between observed refs, scrolling them into view when supported. "
            "Both endpoints must fit in the viewport together."
        ),
    )
    async def drag(
        self,
        source_ref: Annotated[str, _REF],
        target_ref: Annotated[str, _REF],
        duration_seconds: Annotated[float, _DRAG_DURATION] = 0.5,
    ) -> Effect:
        prepared = await self._targets.locate(ref=source_ref)
        target = await self._targets.locate(ref=target_ref)
        # Revealing is sequential (the second scroll may move the first ref);
        # the final hit-tests are independent.
        start, end = await asyncio.gather(
            self._targets.locate(ref=source_ref, scroll=False),
            self._targets.locate(ref=target_ref, scroll=False),
        )
        record_point("viewport", start, endpoint="start")
        record_point("viewport", end, endpoint="end")
        await self._input.mouse.drag(
            start=start, end=end, duration_seconds=duration_seconds
        )
        return Effect(
            "Drag dispatched; inspect the destination.",
            prepared_scroll=prepared.scrolled or target.scrolled,
        )


def _click_message(count: ClickCount, button: ClickButton, new_tab: bool) -> str:
    gesture = "right click" if button == "right" else "click"
    if count == 2:
        gesture = "double " + gesture
    if new_tab:
        gesture = "new-tab click"
    return gesture.capitalize() + " dispatched."


def _image_point(snapshot: Snapshot | CapturedImage, point: Point) -> Point:
    if snapshot.geometry is not None:
        x, y = snapshot.geometry.point(point.x, point.y)
        return Point(x=x, y=y)
    if point.x >= snapshot.width or point.y >= snapshot.height:
        raise BrowserError("Point is outside the observed viewport")
    return point
