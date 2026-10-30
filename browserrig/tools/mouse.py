from typing import Annotated, Literal

from harnessed import Inject, Plugin, SystemSection, tool
from pydantic import Field

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.core.kinds import ActionKind, DragMode
from browserrig.core.modes import DomMode
from browserrig.observation.models import Snapshot
from browserrig.observation.plugin import Observe

from .execution import Actions, Effect

type _ClickCount = Annotated[
    Literal[1, 2], Field(description="2 = native double click (open, edit, select word)")
]


class MouseTools(Plugin, needs=(Actions, Observe)):
    _observe: Inject[Observe]

    coordinates = SystemSection(
        title="Screenshot coordinates",
        text=(
            "Coordinates are measured in pixels from the top-left of the latest screenshot. "
            "Observe again if the tab or document changes before pointing."
        ),
    )

    def _dom_enabled(self) -> bool:
        return isinstance(self._observe.mode, DomMode)

    @tool(description="Click screenshot coordinates; count=2 performs a native double click.")
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: _ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def click(tab: Tab) -> Effect:
            snapshot = self._observe.snapshot
            assert snapshot is not None
            point = _image_point(snapshot, Point(x=x, y=y))
            await tab.mouse.click(point, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Coordinate click dispatched."
            )

        return await actions.run(kind=_click_kind(count), operation=click, expects_change=True)

    @tool(description="Scroll the visible page vertically by CSS pixels.")
    async def scroll(
        self,
        delta_y: Annotated[float, Field(ge=-10000, le=10000)],
        *,
        actions: Inject[Actions],
    ) -> str:
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
        description=(
            "Drag between screenshot points. Use html5 for a native draggable/DataTransfer source."
        )
    )
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        mode: DragMode = DragMode.POINTER,
        *,
        actions: Inject[Actions],
    ) -> str:
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

        return await actions.run(kind=ActionKind.DRAG, operation=drag, expects_change=True)

    # DOM mode deliberately also supports pointing at unreferenced screenshot regions.
    @tool(
        enabled=_dom_enabled,
        description="Click a current DOM ref; count=2 performs a native double click.",
    )
    async def click(
        self,
        ref: str,
        count: _ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def click(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await tab.mouse.move_to(point)
            # Hover may reveal an overlay or move the target; hit-test again.
            current = await actions.element_point(tab=tab, ref=ref, scroll=False)
            await tab.mouse.click(current, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Click dispatched.",
                prepared_scroll=point.scrolled,
            )

        return await actions.run(kind=_click_kind(count), operation=click, expects_change=True)

    @tool(
        enabled=_dom_enabled,
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
    ) -> str:
        async def drag(tab: Tab) -> Effect:
            _, source = await self._observe.element(tab, source_ref)
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


def _click_kind(count: _ClickCount) -> ActionKind:
    return ActionKind.DOUBLE_CLICK if count == 2 else ActionKind.CLICK


def _image_point(snapshot: Snapshot, point: Point) -> Point:
    if snapshot.geometry is not None:
        x, y = snapshot.geometry.point(point.x, point.y)
        return Point(x=x, y=y)
    if point.x >= snapshot.width or point.y >= snapshot.height:
        raise BrowserError("Point is outside the observed viewport")
    return point
