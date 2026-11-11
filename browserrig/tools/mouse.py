import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from harnessed import (
    Instructions,
    Plugin,
    SystemPrompt,
    ToolError,
)
from harnessed.kernel import needs
from pydantic import Field

from browserrig.browser import Browser
from browserrig.core import ActionKind, BrowserError, Point
from browserrig.core import browser_tool as tool
from browserrig.observation import BrowserPerception, CapturedImage, Snapshot

from .effects import Effect
from .execution import Actions

type _ClickCount = Annotated[
    Literal[1, 2],
    Field(description="Use 2 for a native double click."),
]
type _ClickButton = Literal["left", "right"]
type _NewTab = Annotated[
    bool,
    Field(description="Open the link in a new tab and activate it."),
]


_INSTRUCTIONS = Instructions(
    title="Screenshot coordinates",
    text=(
        "Point in pixels from the top-left of the newest screenshot still in context; "
        "crop and scale map back to the viewport. Without an image, use viewport CSS pixels. "
        "After a tab or document change, request a fresh screenshot before pointing. "
        "Clicks that open a new tab activate it."
    ),
)


class PointerTools(Plugin):
    """Mouse input by screenshot coordinates, plus by observed ref when refs exist.

    Coordinates also reach unreferenced regions, so text-only agents keep them too.
    """

    _browser = needs(Browser)
    _observe = needs(BrowserPerception)
    _actions = needs(Actions)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @tool(
        kind=ActionKind.MOVE_MOUSE,
        description="Hover without clicking; address a ref or both coordinates.",
    )
    async def move_mouse(
        self,
        x: Annotated[float | None, Field(ge=0)] = None,
        y: Annotated[float | None, Field(ge=0)] = None,
        ref: str | None = None,
    ) -> Effect:
        if ref is not None and (x is not None or y is not None):
            raise ToolError("Provide either ref or coordinates, not both")
        if ref is None and (x is None or y is None):
            raise ToolError("Provide ref, or both x and y")

        if ref is not None:
            point = await self._actions.element_point(ref=ref)
            await self._browser.input.mouse.move_to(point)
            return Effect(
                "Cursor moved onto the ref without clicking.",
                prepared_scroll=point.scrolled,
            )
        assert x is not None and y is not None
        point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
        await self._browser.input.mouse.move_to(point)
        return Effect("Cursor moved without clicking.")

    @tool(
        kind=ActionKind.CLICK_AT,
        description="Click at screenshot or viewport coordinates.",
    )
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: _ClickCount = 1,
        button: _ClickButton = "left",
        new_tab: _NewTab = False,
    ) -> Effect:
        _check_new_tab(new_tab, count, button)

        point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
        if new_tab:
            # Arrive first, so the key is held for the click alone.
            await self._browser.input.mouse.move_to(point)
        async with self._new_tab_keys(new_tab) as modifiers:
            await self._browser.input.mouse.click(
                point, count=count, button=button, modifiers=modifiers
            )
        return Effect(
            _click_message(count, button, new_tab),
            break_chain=button == "right",
            opens_tab=new_tab,
        )

    @tool(
        kind=ActionKind.DRAG_AT,
        description="Drag between screenshot points.",
    )
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration: Annotated[
            float, Field(ge=0.05, le=5, description="Drag duration in seconds.")
        ] = 0.5,
    ) -> Effect:
        await self._browser.input.mouse.drag(
            start=_image_point(self._observe.coordinate_source(), start),
            end=_image_point(self._observe.coordinate_source(), end),
            duration=duration,
        )
        return Effect("Drag dispatched; inspect the destination.")

    @tool(
        kind=ActionKind.CLICK,
        chainable=True,
        description="Click an observed ref, revealing it first when needed.",
    )
    async def click(
        self,
        ref: str,
        count: _ClickCount = 1,
        button: _ClickButton = "left",
        new_tab: _NewTab = False,
    ) -> Effect:
        _check_new_tab(new_tab, count, button)

        point = await self._actions.element_point(ref=ref)
        await self._browser.input.mouse.move_to(point)
        if change := await self._actions.page_change(after_input=False):
            return Effect(
                f"Hover changed the page: {change} The click was not dispatched. "
                "Inspect the next observation before choosing a target.",
                prepared_scroll=point.scrolled,
                break_chain=True,
            )
        # Hover may reveal an overlay or move the target; hit-test again.
        current = await self._actions.element_point(ref=ref, scroll=False)
        if new_tab:
            # Arrive first, so the key is held for the click alone.
            await self._browser.input.mouse.move_to(current)
        async with self._new_tab_keys(new_tab) as modifiers:
            await self._browser.input.mouse.click(
                current, count=count, button=button, modifiers=modifiers
            )
        return Effect(
            _click_message(count, button, new_tab),
            prepared_scroll=point.scrolled,
            break_chain=button == "right",
            opens_tab=new_tab,
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
        source_ref: str,
        target_ref: str,
        duration: Annotated[
            float, Field(ge=0.05, le=5, description="Drag duration in seconds.")
        ] = 0.5,
    ) -> Effect:
        prepared = await self._actions.element_point(ref=source_ref)
        target = await self._actions.element_point(ref=target_ref)
        # Revealing is sequential (the second scroll may move the first ref);
        # the final hit-tests are independent.
        start, end = await asyncio.gather(
            self._actions.element_point(ref=source_ref, scroll=False),
            self._actions.element_point(ref=target_ref, scroll=False),
        )
        await self._browser.input.mouse.drag(start=start, end=end, duration=duration)
        return Effect(
            "Drag dispatched; inspect the destination.",
            prepared_scroll=prepared.scrolled or target.scrolled,
        )

    @asynccontextmanager
    async def _new_tab_keys(self, new_tab: bool) -> AsyncGenerator[int]:
        """Hold the key that opens a link in a new tab, so viewers see it pressed."""
        if not new_tab:
            yield 0
            return
        key = await self._browser.tabs.link_modifier()
        async with self._browser.input.keyboard.hold(key) as modifiers:
            yield modifiers


def _check_new_tab(new_tab: bool, count: int, button: str) -> None:
    if new_tab and (count != 1 or button != "left"):
        raise ToolError("new_tab needs a single left click")


def _click_message(
    count: Literal[1, 2], button: Literal["left", "right"], new_tab: bool = False
) -> str:
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
