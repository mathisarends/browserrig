from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from typing import Literal

from cdpify import CdpSession
from cdpify.domains.input import DragData, DragInterceptedEvent, MouseButton

from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.core.kinds import DragMode, MouseEventKind
from browserrig.events import (
    CursorMovedEvent,
    CursorStateEvent,
    InputEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    ScrolledEvent,
)

from .pointer import ease, movement


class Mouse:
    def __init__(
        self,
        cdp: CdpSession,
        *,
        emit: Callable[[InputEvent], Awaitable[None]],
        layout_changed: Callable[[], None] = lambda: None,
    ) -> None:
        self._cdp = cdp
        self._emit = emit
        # Hover, presses, drags and wheel input can move content, including iframes.
        self._layout_changed = layout_changed
        self.position = Point(x=0, y=0)
        self._cursor_initialized = False

    async def initialize_cursor(self) -> None:
        """Seed a tab's native pointer near the center, without animating from the origin."""
        if not self._cursor_initialized:
            metrics = await self._cdp.page.get_layout_metrics()
            viewport = metrics.css_layout_viewport
            await self._dispatch(
                MouseEventKind.MOVED,
                Point(
                    x=random.uniform(viewport.client_width * 0.4, viewport.client_width * 0.6),
                    y=random.uniform(viewport.client_height * 0.4, viewport.client_height * 0.6),
                ),
            )
            self._cursor_initialized = True
        await self.publish_cursor()

    async def publish_cursor(self) -> None:
        await self._emit(CursorStateEvent(x=self.position.x, y=self.position.y))

    async def move_to(self, point: Point) -> None:
        path = movement(self.position, point)
        cp1, cp2 = path.control_points
        await self._emit(
            CursorMovedEvent(
                from_position=(path.start.x, path.start.y),
                to_position=(point.x, point.y),
                control_point_1=cp1,
                control_point_2=cp2,
                duration=path.duration,
            )
        )
        try:
            for step in range(1, path.steps + 1):
                current = path.point(step / path.steps)
                await self._dispatch(MouseEventKind.MOVED, current)
                if path.duration:
                    await asyncio.sleep(path.duration / path.steps)
        finally:
            await self.publish_cursor()

    async def click(self, point: Point, *, count: Literal[1, 2] = 1) -> None:
        await self.move_to(point)
        for click_count in range(1, count + 1):
            try:
                await self._dispatch(
                    MouseEventKind.PRESSED, point, buttons=1, click_count=click_count
                )
            finally:
                await self._dispatch(
                    MouseEventKind.RELEASED, point, buttons=0, click_count=click_count
                )

    async def drag(
        self,
        *,
        start: Point,
        end: Point,
        duration: float,
        mode: DragMode = DragMode.POINTER,
    ) -> None:
        """Drag with the left button; the button is released even when interrupted."""
        distance = math.hypot(end.x - start.x, end.y - start.y)
        if distance < 1:
            raise BrowserError("Drag source and destination must be different")
        cdp = self._cdp
        await self.move_to(start)
        current = start
        data: DragData | None = None
        dropped = False
        start_fraction = 0.0
        try:
            if mode is DragMode.HTML5:
                await cdp.input.set_intercept_drags(enabled=True)
            await self._dispatch(MouseEventKind.PRESSED, start, buttons=1, click_count=1)
            if mode is DragMode.HTML5:
                # Subscribe before crossing the native drag threshold.
                async with cdp.listen(DragInterceptedEvent, timeout=2) as subscription:
                    start_fraction = min(12 / distance, 1)
                    current = Point(
                        x=start.x + (end.x - start.x) * start_fraction,
                        y=start.y + (end.y - start.y) * start_fraction,
                    )
                    await self._dispatch(MouseEventKind.MOVED, current, buttons=1)
                    data = (await anext(subscription)).data
                await cdp.input.dispatch_drag_event(
                    type="dragEnter", x=current.x, y=current.y, data=data
                )
            steps = max(3, math.ceil(duration * 30))
            for index in range(1, steps + 1):
                fraction = start_fraction + (1 - start_fraction) * index / steps
                current = Point(
                    x=start.x + (end.x - start.x) * fraction,
                    y=start.y + (end.y - start.y) * fraction,
                )
                if data is not None:
                    await cdp.input.dispatch_drag_event(
                        type="dragOver", x=current.x, y=current.y, data=data
                    )
                    self.position = current
                    self._layout_changed()
                    await self._emit(CursorStateEvent(x=current.x, y=current.y, buttons=1))
                else:
                    await self._dispatch(MouseEventKind.MOVED, current, buttons=1)
                await asyncio.sleep(duration / steps)
            if data is not None:
                await cdp.input.dispatch_drag_event(type="drop", x=end.x, y=end.y, data=data)
                dropped = True
                self._layout_changed()
        finally:
            await self._release_drag(current, data, dropped=dropped, mode=mode)

    async def scroll(self, *, point: Point, delta_y: float, delta_x: float = 0) -> None:
        if delta_y == 0 and delta_x == 0:
            return
        await self.move_to(point)
        duration = min(0.4, max(0.08, max(abs(delta_x), abs(delta_y)) * 0.0003))
        steps = max(3, round(duration * 60))
        previous = 0.0
        for index in range(1, steps + 1):
            current = ease(index / steps)
            await self._cdp.input.dispatch_mouse_event(
                type=MouseEventKind.WHEEL.value,
                x=point.x,
                y=point.y,
                delta_x=delta_x * (current - previous),
                delta_y=delta_y * (current - previous),
            )
            self._layout_changed()
            previous = current
            await asyncio.sleep(duration / steps)
        await self._emit(
            ScrolledEvent(x=point.x, y=point.y, delta_x=delta_x, delta_y=delta_y, duration=duration)
        )

    async def _dispatch(
        self,
        kind: Literal[MouseEventKind.MOVED, MouseEventKind.PRESSED, MouseEventKind.RELEASED],
        point: Point,
        *,
        buttons: int = 0,
        click_count: int = 0,
    ) -> None:
        await self._cdp.input.dispatch_mouse_event(
            type=kind.value,
            x=point.x,
            y=point.y,
            button=MouseButton.LEFT
            if buttons or kind is MouseEventKind.RELEASED
            else MouseButton.NONE,
            buttons=buttons,
            click_count=click_count,
        )
        self.position = point
        self._layout_changed()
        if kind is MouseEventKind.MOVED:
            if buttons:
                await self._emit(CursorStateEvent(x=point.x, y=point.y, buttons=buttons))
            return
        event_type = PointerPressedEvent if kind is MouseEventKind.PRESSED else PointerReleasedEvent
        await self._emit(event_type(x=point.x, y=point.y, click_count=click_count))

    async def _release_drag(
        self, point: Point, data: DragData | None, *, dropped: bool, mode: DragMode
    ) -> None:
        try:
            if data is not None and not dropped:
                await self._cdp.input.dispatch_drag_event(
                    type="dragCancel", x=point.x, y=point.y, data=data
                )
        finally:
            try:
                await self._dispatch(MouseEventKind.RELEASED, point, buttons=0, click_count=1)
            finally:
                if mode is DragMode.HTML5:
                    await self._cdp.input.set_intercept_drags(enabled=False)
