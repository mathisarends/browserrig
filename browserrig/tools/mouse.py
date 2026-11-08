from typing import Annotated, Literal

from harnessed import (
    Inject,
    Instructions,
    Plugin,
    SystemPrompt,
    ToolError,
    ToolResult,
)
from harnessed.kernel import needs
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind, BrowserError, Point
from browserrig.core import browser_tool as tool
from browserrig.observation import BrowserPerception, CapturedImage, Snapshot

from .effects import Effect
from .execution import Actions

type _ClickCount = Annotated[
    Literal[1, 2],
    Field(description="2 = native double click (open, edit, select word)"),
]
type _ClickButton = Annotated[
    Literal["left", "right"], Field(description="Mouse button to press.")
]
type _ScrollDelta = Annotated[float, Field(ge=-10000, le=10000)]


_INSTRUCTIONS = Instructions(
    title="Screenshot coordinates",
    text=(
        "Coordinates are pixels from the top-left of the newest shown image for this document; "
        "region and canvas images are mapped back to the viewport automatically. "
        "A red cursor marker shows the pointer position when the screenshot was captured; "
        "it is omitted when outside the image. "
        "Observe again if the tab or document changes before pointing."
    ),
)


class PointerTools(Plugin, needs=(Actions,)):
    """Mouse input by screenshot coordinates, plus by observed ref when refs exist.

    Coordinates also reach unreferenced regions, so text-only agents keep them too.
    """

    _browser = needs(Browser)
    _observe = needs(BrowserPerception)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @tool(
        kind=ActionKind.MOVE_MOUSE,
        description=(
            "Move the cursor to image or viewport coordinates without clicking. "
            "Use before scroll to target a particular scrollable area, or to hover."
        ),
    )
    async def move_mouse(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def move(_tab: Tab) -> Effect:
            point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
            await self._browser.input.mouse.move_to(point)
            return Effect("Cursor moved without clicking.")

        return await actions.run(kind=ActionKind.MOVE_MOUSE, operation=move)

    @tool(
        kind=ActionKind.CLICK_AT,
        description=(
            "Automatically move the cursor to image or viewport coordinates and click there; "
            "count=2 performs a native double click; button=right performs a right click."
        ),
    )
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: _ClickCount = 1,
        button: _ClickButton = "left",
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def click(_tab: Tab) -> Effect:
            point = _image_point(self._observe.coordinate_source(), Point(x=x, y=y))
            await self._browser.input.mouse.click(point, count=count, button=button)
            return Effect(_click_message(count, button), break_chain=button == "right")

        return await actions.run(
            kind=ActionKind.CLICK_AT, operation=click, expects_change=True
        )

    @tool(
        kind=ActionKind.SCROLL,
        description=(
            "Scroll by CSS pixels at the current cursor position: delta_y down (negative up), "
            "delta_x right (negative left), e.g. for carousels or wide tables. "
            "Use move_mouse first to target a particular scrollable area."
        ),
    )
    async def scroll(
        self,
        delta_y: _ScrollDelta = 0,
        delta_x: _ScrollDelta = 0,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        if delta_y == 0 and delta_x == 0:
            raise ToolError("Provide a non-zero delta_y or delta_x")

        async def scroll(_tab: Tab) -> Effect:
            await self._browser.input.mouse.scroll(delta_y=delta_y, delta_x=delta_x)
            return Effect("Scroll dispatched.")

        return await actions.run(
            kind=ActionKind.SCROLL,
            operation=scroll,
        )

    @tool(
        kind=ActionKind.DRAG_AT,
        description="Drag between screenshot points.",
    )
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def drag(_tab: Tab) -> Effect:
            await self._browser.input.mouse.drag(
                start=_image_point(self._observe.coordinate_source(), start),
                end=_image_point(self._observe.coordinate_source(), end),
                duration=duration,
            )
            return Effect("Drag dispatched; inspect the destination.")

        return await actions.run(
            kind=ActionKind.DRAG_AT, operation=drag, expects_change=True
        )

    @tool(
        kind=ActionKind.CLICK,
        chainable=True,
        description=(
            "Automatically move the cursor to a current observed ref and click it; "
            "count=2 performs a native double click; "
            "button=right performs a right click."
        ),
    )
    async def click(
        self,
        ref: str,
        count: _ClickCount = 1,
        button: _ClickButton = "left",
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def click(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await self._browser.input.mouse.move_to(point)
            if change := await actions.page_change(tab, after_input=False):
                return Effect(
                    f"Hover changed the page: {change} The click was not dispatched. "
                    "Inspect the next observation before choosing a target.",
                    prepared_scroll=point.scrolled,
                    break_chain=True,
                )
            # Hover may reveal an overlay or move the target; hit-test again.
            current = await actions.element_point(tab=tab, ref=ref, scroll=False)
            await self._browser.input.mouse.click(current, count=count, button=button)
            return Effect(
                _click_message(count, button),
                prepared_scroll=point.scrolled,
                break_chain=button == "right",
            )

        return await actions.run(
            kind=ActionKind.CLICK, operation=click, expects_change=True
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
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def drag(tab: Tab) -> Effect:
            prepared = await actions.element_point(tab=tab, ref=source_ref)
            target = await actions.element_point(tab=tab, ref=target_ref)
            start = await actions.element_point(tab=tab, ref=source_ref, scroll=False)
            end = await actions.element_point(tab=tab, ref=target_ref, scroll=False)
            await self._browser.input.mouse.drag(
                start=start, end=end, duration=duration
            )
            return Effect(
                "Drag dispatched; inspect the destination.",
                prepared_scroll=prepared.scrolled or target.scrolled,
            )

        return await actions.run(
            kind=ActionKind.DRAG, operation=drag, expects_change=True
        )


def _click_message(count: Literal[1, 2], button: Literal["left", "right"]) -> str:
    gesture = "right click" if button == "right" else "click"
    if count == 2:
        gesture = "double " + gesture
    return gesture.capitalize() + " dispatched."


def _image_point(snapshot: Snapshot | CapturedImage, point: Point) -> Point:
    if snapshot.geometry is not None:
        x, y = snapshot.geometry.point(point.x, point.y)
        return Point(x=x, y=y)
    if point.x >= snapshot.width or point.y >= snapshot.height:
        raise BrowserError("Point is outside the observed viewport")
    return point
