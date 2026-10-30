import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from typing import Literal

from cdpify import CdpSession
from cdpify.domains.input import MouseButton

from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.core.kinds import CursorStyle, MouseEventKind
from browserrig.events import (
    CursorMovedEvent,
    CursorStateEvent,
    CursorStyleEvent,
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
        cursor_style: Callable[[Point], Awaitable[CursorStyle | None]] | None = None,
    ) -> None:
        self._cdp = cdp
        self._emit = emit
        self._cursor_style = cursor_style
        # Hover, presses, drags and wheel input can move content, including iframes.
        self._layout_changed = layout_changed
        self.position = Point(x=0, y=0)
        # Last CSS cursor reported to viewers; None until the page has been asked.
        self.style: CursorStyle | None = None
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
        """Republish position and known cursor shape for viewers that attached late."""
        await self._publish_position()
        if self.style is not None:
            await self._emit(CursorStyleEvent(style=self.style))

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
            await self._publish_position()
        await self._refresh_style()

    async def click(
        self,
        point: Point,
        *,
        count: Literal[1, 2] = 1,
        button: Literal["left", "right"] = "left",
    ) -> None:
        await self.move_to(point)
        mouse_button = MouseButton(button)
        buttons = 2 if button == "right" else 1
        for click_count in range(1, count + 1):
            try:
                await self._dispatch(
                    MouseEventKind.PRESSED,
                    point,
                    button=mouse_button,
                    buttons=buttons,
                    click_count=click_count,
                )
            finally:
                await self._dispatch(
                    MouseEventKind.RELEASED,
                    point,
                    button=mouse_button,
                    buttons=0,
                    click_count=click_count,
                )

    async def drag(
        self,
        *,
        start: Point,
        end: Point,
        duration: float,
    ) -> None:
        """Let the browser handle the drag gesture; always release the left button."""
        distance = math.hypot(end.x - start.x, end.y - start.y)
        if distance < 1:
            raise BrowserError("Drag source and destination must be different")
        await self.move_to(start)
        current = start
        try:
            await self._dispatch(MouseEventKind.PRESSED, start, buttons=1, click_count=1)
            # CDP's mouse input handles native drag-and-drop as well as pointer gestures.
            steps = max(3, math.ceil(duration * 30))
            for index in range(1, steps + 1):
                fraction = index / steps
                current = Point(
                    x=start.x + (end.x - start.x) * fraction,
                    y=start.y + (end.y - start.y) * fraction,
                )
                await self._dispatch(MouseEventKind.MOVED, current, buttons=1)
                await asyncio.sleep(duration / steps)
            # Entering the drop target may only fire dragenter. Move again there so
            # its dragover handler can accept the drop before the button is released.
            await self._dispatch(MouseEventKind.MOVED, end, buttons=1)
        except BaseException:
            # Cancel a native drag before releasing so an interrupted gesture cannot drop.
            await self._cdp.input.cancel_dragging()
            raise
        finally:
            await self._dispatch(MouseEventKind.RELEASED, current, buttons=0, click_count=1)

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
        # Scrolled content can put a different element under the resting pointer.
        await self._refresh_style()

    async def _publish_position(self) -> None:
        await self._emit(CursorStateEvent(x=self.position.x, y=self.position.y))

    async def _refresh_style(self) -> None:
        if self._cursor_style is None:
            return
        style = await self._cursor_style(self.position)
        if style is not None and style != self.style:
            self.style = style
            await self._emit(CursorStyleEvent(style=style))

    async def _dispatch(
        self,
        kind: Literal[MouseEventKind.MOVED, MouseEventKind.PRESSED, MouseEventKind.RELEASED],
        point: Point,
        *,
        button: MouseButton = MouseButton.LEFT,
        buttons: int = 0,
        click_count: int = 0,
    ) -> None:
        await self._cdp.input.dispatch_mouse_event(
            type=kind.value,
            x=point.x,
            y=point.y,
            button=button if buttons or kind is MouseEventKind.RELEASED else MouseButton.NONE,
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
        await self._emit(
            event_type(x=point.x, y=point.y, click_count=click_count, button=button.value)
        )
