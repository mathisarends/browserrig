import asyncio
from typing import Annotated, Literal

from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.models import Point
from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, DragMode

from .execution import Actions, Effect
from .gestures import click as click_gesture
from .gestures import drag as drag_gesture
from .gestures import image_point

type ClickCount = Annotated[
    Literal[1, 2], Field(description="2 = native double click (open, edit, select word)")
]


class PointerTools(Plugin, needs=(Actions,)):
    @tool
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        count: ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Click screenshot coordinates; count=2 performs a native double click."""

        async def click(tab: Tab) -> Effect:
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            point = image_point(snapshot, Point(x=x, y=y))
            await click_gesture(tab, point=point, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Coordinate click dispatched."
            )

        return await actions.run(kind=_click_kind(count), operation=click, expects_change=True)

    @tool
    async def press_key(
        self,
        key: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Press a page key, optionally with modifiers, e.g. Enter, Tab or Control+a."""

        async def press(tab: Tab) -> Effect:
            await tab.press_key(key)
            return Effect("Key dispatched.")

        return await actions.run(
            kind=ActionKind.PRESS,
            operation=press,
        )

    @tool
    async def scroll(
        self,
        delta_y: Annotated[float, Field(ge=-10000, le=10000)],
        *,
        actions: Inject[Actions],
    ) -> str:
        """Scroll the visible page vertically by CSS pixels."""

        async def scroll(tab: Tab) -> Effect:
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            await tab.cdp.input.dispatch_mouse_event(
                type="mouseWheel",
                x=snapshot.width / 2,
                y=snapshot.height / 2,
                delta_x=0,
                delta_y=delta_y,
            )
            await asyncio.sleep(0.05)
            return Effect("Scroll dispatched.")

        return await actions.run(
            kind=ActionKind.SCROLL,
            operation=scroll,
        )

    @tool(readonly=True)
    async def wait(self, seconds: Annotated[float, Field(ge=0, le=10)] = 1) -> str:
        """Wait briefly for an expected asynchronous page update, then observe again."""
        await asyncio.sleep(seconds)
        return "Wait completed; observe the current state."

    @tool
    async def drag_at(
        self,
        start: Point,
        end: Point,
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        mode: DragMode = DragMode.POINTER,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Drag between screenshot points. Use html5 for a native draggable/DataTransfer source."""

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
    @tool
    async def click(
        self,
        ref: str,
        count: ClickCount = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Click a current DOM ref; count=2 performs a native double click."""

        async def click(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await click_gesture(tab, point=point, count=count)
            return Effect(
                "Double click dispatched." if count == 2 else "Click dispatched.",
                prepared_scroll=point.scrolled,
            )

        return await actions.run(kind=_click_kind(count), operation=click, expects_change=True)

    @tool
    async def drag(
        self,
        source_ref: str,
        target_ref: str,
        duration: Annotated[float, Field(ge=0.05, le=5)] = 0.5,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Drag between visible DOM refs; native draggable sources use HTML5 DataTransfer."""

        async def drag(tab: Tab) -> Effect:
            _, source = await actions.observe.element(tab, source_ref)
            start = await actions.element_point(tab=tab, ref=source_ref, scroll=False)
            end = await actions.element_point(tab=tab, ref=target_ref, scroll=False)
            mode = DragMode.HTML5 if source.draggable else DragMode.POINTER
            await drag_gesture(tab, start=start, end=end, duration=duration, mode=mode)
            return Effect("Drag dispatched; inspect the destination.")

        return await actions.run(kind=ActionKind.DRAG, operation=drag, expects_change=True)


def _click_kind(count: ClickCount) -> ActionKind:
    return ActionKind.DOUBLE_CLICK if count == 2 else ActionKind.CLICK
