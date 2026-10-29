import asyncio
from typing import Annotated, Literal

from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.models import Point
from browserrig.browser.tab import Tab
from browserrig.events import WaitingEvent
from browserrig.kinds import ActionKind, DragMode

from .execution import Actions, Effect
from .gestures import click as click_gesture
from .gestures import drag as drag_gesture
from .gestures import image_point

type ClickCount = Annotated[
    Literal[1, 2], Field(description="2 = native double click (open, edit, select word)")
]


class PointerTools(Plugin, needs=(Actions,)):
    @tool(description="Click screenshot coordinates; count=2 performs a native double click.")
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def click(tab: Tab) -> Effect:
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            point = image_point(snapshot, Point(x=x, y=y))
            await click_gesture(tab, point=point, count=count)
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
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            await tab.input.scroll(
                point=Point(x=snapshot.width / 2, y=snapshot.height / 2), delta_y=delta_y
            )
            return Effect("Scroll dispatched.")

        return await actions.run(
            kind=ActionKind.SCROLL,
            operation=scroll,
        )

    @tool(
        readonly=True,
        description="Wait briefly for an expected asynchronous page update, then observe again.",
    )
    async def wait(
        self,
        seconds: Annotated[float, Field(ge=0, le=10)] = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        await actions.browser.active_tab.input.emit(WaitingEvent(duration=seconds))
        await asyncio.sleep(seconds)
        return "Wait completed; observe the current state."

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
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            await drag_gesture(
                tab,
                start=image_point(snapshot, start),
                end=image_point(snapshot, end),
                duration=duration,
                mode=mode,
            )
            return Effect("Drag dispatched; inspect the destination.")

        return await actions.run(kind=ActionKind.DRAG, operation=drag, expects_change=True)


class InteractionTools(PointerTools):
    @tool(description="Click a current DOM ref; count=2 performs a native double click.")
    async def click(
        self,
        ref: str,
        count: ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def click(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await tab.input.move_to(point)
            # Hover may reveal an overlay or move the target; hit-test again.
            current = await actions.element_point(tab=tab, ref=ref, scroll=False)
            await click_gesture(tab, point=current, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Click dispatched.",
                prepared_scroll=point.scrolled,
            )

        return await actions.run(kind=_click_kind(count), operation=click, expects_change=True)

    @tool(
        description=(
            "Drag between DOM refs, scrolling them into view first. Both endpoints must fit "
            "in the viewport together; native draggable sources use HTML5 DataTransfer."
        )
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
            _, source = await actions.observe.element(tab, source_ref)
            prepared = await actions.element_point(tab=tab, ref=source_ref)
            target = await actions.element_point(tab=tab, ref=target_ref)
            start = await actions.element_point(tab=tab, ref=source_ref, scroll=False)
            end = await actions.element_point(tab=tab, ref=target_ref, scroll=False)
            mode = DragMode.HTML5 if source.draggable else DragMode.POINTER
            await drag_gesture(tab, start=start, end=end, duration=duration, mode=mode)
            return Effect(
                "Drag dispatched; inspect the destination.",
                prepared_scroll=prepared.scrolled or target.scrolled,
            )

        return await actions.run(kind=ActionKind.DRAG, operation=drag, expects_change=True)


def _click_kind(count: ClickCount) -> ActionKind:
    return ActionKind.DOUBLE_CLICK if count == 2 else ActionKind.CLICK
