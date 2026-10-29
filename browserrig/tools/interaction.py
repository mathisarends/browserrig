import asyncio
from typing import Annotated

from cdpify.domains.input import MouseButton
from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, ElementOperation

from .execution import Actions, Effect


class PointerTools(Plugin, needs=(Actions,)):
    @tool
    async def click_at(
        self,
        x: Annotated[float, Field(ge=0)],
        y: Annotated[float, Field(ge=0)],
        *,
        actions: Inject[Actions],
    ) -> str:
        """Click screenshot coordinates, applying the canvas crop mapping when present."""

        async def click(tab: Tab) -> Effect:
            snapshot = actions.observe.snapshot
            assert snapshot is not None
            if snapshot.geometry:
                px, py = snapshot.geometry.point(x, y)
            else:
                if x >= snapshot.width or y >= snapshot.height:
                    raise ValueError("Coordinates exceed the observed viewport")
                px, py = x, y
            await _click(tab, px, py)
            return Effect("Coordinate click dispatched.")

        return await actions.run(kind=ActionKind.CLICK, operation=click, expects_change=True)

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


class InteractionTools(PointerTools):
    @tool
    async def click(
        self,
        ref: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Click an element ref from the latest DOM observation."""

        async def click(tab: Tab) -> Effect:
            frame, _ = await actions.observe.element(tab, ref)
            point = await actions.element_call(tab=tab, ref=ref, operation=ElementOperation.POINT)
            await _click(tab, point["x"] + frame.x, point["y"] + frame.y)
            return Effect("Click dispatched.", point["scrolled"])

        return await actions.run(kind=ActionKind.CLICK, operation=click, expects_change=True)


async def _click(tab: Tab, x: float, y: float) -> None:
    await tab.cdp.input.dispatch_mouse_event(type="mouseMoved", x=x, y=y)
    await tab.cdp.input.dispatch_mouse_event(
        type="mousePressed", x=x, y=y, button=MouseButton.LEFT, click_count=1
    )
    await tab.cdp.input.dispatch_mouse_event(
        type="mouseReleased", x=x, y=y, button=MouseButton.LEFT, click_count=1
    )
