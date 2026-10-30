from typing import Annotated, Literal

from harnessed import Inject, Plugin, SystemSection, ToolResult
from pydantic import Field

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.core.kinds import ActionKind, DragMode
from browserrig.core.tools import browser_tool as tool
from browserrig.observation.models import Snapshot
from browserrig.observation.plugin import Observe, has_dom_refs

from .execution import Actions, Effect

type _ClickCount = Annotated[
    Literal[1, 2], Field(description="2 = native double click (open, edit, select word)")
]


class MouseTools(Plugin, needs=(Actions, Observe)):
    _observe: Inject[Observe]

    coordinates = SystemSection(
        title="Screenshot coordinates",
        text=(
            "Coordinates are pixels from the top-left of the current observation's image; "
            "region and canvas images are mapped back to the viewport automatically. "
            "Observe again if the tab or document changes before pointing."
        ),
    )

    @tool(
        kind=ActionKind.CLICK_AT,
        description=(
            "Click image or viewport coordinates, such as inside a listed canvas; "
            "count=2 performs a native double click."
        ),
    )
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: _ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def click(tab: Tab) -> Effect:
            snapshot = self._observe.snapshot
            assert snapshot is not None
            point = _image_point(snapshot, Point(x=x, y=y))
            await tab.mouse.click(point, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Coordinate click dispatched."
            )

        return await actions.run(kind=ActionKind.CLICK_AT, operation=click, expects_change=True)

    @tool(kind=ActionKind.SCROLL, description="Scroll the visible page vertically by CSS pixels.")
    async def scroll(
        self,
        delta_y: Annotated[float, Field(ge=-10000, le=10000)],
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def scroll(tab: Tab) -> Effect:
            snapshot = self._observe.snapshot
            assert snapshot is not None
            await tab.mouse.scroll(
                point=Point(x=snapshot.width / 2, y=snapshot.height / 2), delta_y=delta_y
            )
            return Effect("Scroll dispatched.")

        return await actions.run(
            kind=ActionKind.SCROLL,
            operation=scroll,
        )

    @tool(
        kind=ActionKind.DRAG_AT,
        description=(
            "Drag between screenshot points. Use html5 for a native draggable/DataTransfer source."
        ),
    )
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        mode: DragMode = DragMode.POINTER,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def drag(tab: Tab) -> Effect:
            snapshot = self._observe.snapshot
            assert snapshot is not None
            await tab.mouse.drag(
                start=_image_point(snapshot, start),
                end=_image_point(snapshot, end),
                duration=duration,
                mode=mode,
            )
            return Effect("Drag dispatched; inspect the destination.")

        return await actions.run(kind=ActionKind.DRAG_AT, operation=drag, expects_change=True)

    # DOM mode deliberately also supports pointing at unreferenced screenshot regions.
    @tool(
        kind=ActionKind.CLICK,
        chainable=True,
        enabled=has_dom_refs,
        description="Click a current DOM ref; count=2 performs a native double click.",
    )
    async def click(
        self,
        ref: str,
        count: _ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def click(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await tab.mouse.move_to(point)
            if change := await actions.page_change(tab):
                return Effect(
                    f"Hover changed the page: {change} The click was not dispatched. "
                    "Inspect the next observation before choosing a target.",
                    prepared_scroll=point.scrolled,
                    break_chain=True,
                )
            # Hover may reveal an overlay or move the target; hit-test again.
            current = await actions.element_point(tab=tab, ref=ref, scroll=False)
            await tab.mouse.click(current, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Click dispatched.",
                prepared_scroll=point.scrolled,
            )

        return await actions.run(kind=ActionKind.CLICK, operation=click, expects_change=True)

    @tool(
        kind=ActionKind.DRAG,
        enabled=has_dom_refs,
        description=(
            "Drag between DOM refs, scrolling them into view first. Both endpoints must fit "
            "in the viewport together; native draggable sources use HTML5 DataTransfer."
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
            source = (await self._observe.element(tab, source_ref)).element
            prepared = await actions.element_point(tab=tab, ref=source_ref)
            target = await actions.element_point(tab=tab, ref=target_ref)
            start = await actions.element_point(tab=tab, ref=source_ref, scroll=False)
            end = await actions.element_point(tab=tab, ref=target_ref, scroll=False)
            mode = DragMode.HTML5 if source.draggable else DragMode.POINTER
            await tab.mouse.drag(start=start, end=end, duration=duration, mode=mode)
            return Effect(
                "Drag dispatched; inspect the destination.",
                prepared_scroll=prepared.scrolled or target.scrolled,
            )

        return await actions.run(kind=ActionKind.DRAG, operation=drag, expects_change=True)


def _image_point(snapshot: Snapshot, point: Point) -> Point:
    if snapshot.geometry is not None:
        x, y = snapshot.geometry.point(point.x, point.y)
        return Point(x=x, y=y)
    if point.x >= snapshot.width or point.y >= snapshot.height:
        raise BrowserError("Point is outside the observed viewport")
    return point
