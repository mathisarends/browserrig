"""Bounded native CDP gestures with unconditional button/interception cleanup."""

import asyncio
import math
from typing import Literal

from cdpify.domains.input import DragData, DragInterceptedEvent, MouseButton

from browserrig.browser.errors import BrowserError
from browserrig.browser.models import Point
from browserrig.browser.tab import Tab
from browserrig.kinds import DragMode
from browserrig.observation.models import Snapshot


def image_point(snapshot: Snapshot, point: Point) -> Point:
    if snapshot.geometry is not None:
        x, y = snapshot.geometry.point(point.x, point.y)
        return Point(x=x, y=y)
    if point.x >= snapshot.width or point.y >= snapshot.height:
        raise BrowserError("Point is outside the observed viewport")
    return point


async def click(tab: Tab, *, point: Point, count: Literal[1, 2] = 1) -> None:
    await tab.cdp.input.dispatch_mouse_event(type="mouseMoved", x=point.x, y=point.y)
    for click_count in range(1, count + 1):
        try:
            await tab.cdp.input.dispatch_mouse_event(
                type="mousePressed",
                x=point.x,
                y=point.y,
                button=MouseButton.LEFT,
                buttons=1,
                click_count=click_count,
            )
        finally:
            await tab.cdp.input.dispatch_mouse_event(
                type="mouseReleased",
                x=point.x,
                y=point.y,
                button=MouseButton.LEFT,
                buttons=0,
                click_count=click_count,
            )


async def drag(
    tab: Tab, *, start: Point, end: Point, duration: float, mode: DragMode = DragMode.POINTER
) -> None:
    distance = math.hypot(end.x - start.x, end.y - start.y)
    if distance < 1:
        raise BrowserError("Drag source and destination must be different")
    await tab.cdp.input.dispatch_mouse_event(type="mouseMoved", x=start.x, y=start.y)
    current = start
    data: DragData | None = None
    dropped = False
    try:
        if mode is DragMode.HTML5:
            await tab.cdp.input.set_intercept_drags(enabled=True)
        await tab.cdp.input.dispatch_mouse_event(
            type="mousePressed",
            x=start.x,
            y=start.y,
            button=MouseButton.LEFT,
            buttons=1,
            click_count=1,
        )
        if mode is DragMode.HTML5:
            # Subscribe before crossing the native drag threshold.
            async with tab.cdp.listen(DragInterceptedEvent, timeout=2) as subscription:
                current = Point(
                    x=start.x + (end.x - start.x) * min(12 / distance, 1),
                    y=start.y + (end.y - start.y) * min(12 / distance, 1),
                )
                await tab.cdp.input.dispatch_mouse_event(
                    type="mouseMoved", x=current.x, y=current.y, button=MouseButton.LEFT, buttons=1
                )
                data = (await anext(subscription)).data
            await tab.cdp.input.dispatch_drag_event(
                type="dragEnter", x=current.x, y=current.y, data=data
            )
        steps = max(3, math.ceil(duration * 30))
        for index in range(1, steps + 1):
            fraction = index / steps
            current = Point(
                x=start.x + (end.x - start.x) * fraction, y=start.y + (end.y - start.y) * fraction
            )
            if data is not None:
                await tab.cdp.input.dispatch_drag_event(
                    type="dragOver", x=current.x, y=current.y, data=data
                )
            else:
                await tab.cdp.input.dispatch_mouse_event(
                    type="mouseMoved", x=current.x, y=current.y, button=MouseButton.LEFT, buttons=1
                )
            await asyncio.sleep(duration / steps)
        if data is not None:
            await tab.cdp.input.dispatch_drag_event(type="drop", x=end.x, y=end.y, data=data)
            dropped = True
    finally:
        try:
            if data is not None and not dropped:
                await tab.cdp.input.dispatch_drag_event(
                    type="dragCancel", x=current.x, y=current.y, data=data
                )
        finally:
            try:
                await tab.cdp.input.dispatch_mouse_event(
                    type="mouseReleased",
                    x=current.x,
                    y=current.y,
                    button=MouseButton.LEFT,
                    buttons=0,
                    click_count=1,
                )
            finally:
                if mode is DragMode.HTML5:
                    await tab.cdp.input.set_intercept_drags(enabled=False)
