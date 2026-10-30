import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from cdpify.domains.input import MouseButton

from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.core.kinds import CursorStyle, MouseEventKind, TabGesture
from browserrig.events import (
    CursorEnteredEvent,
    CursorMovedEvent,
    CursorStateEvent,
    CursorStyleEvent,
    InputEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    ScrolledEvent,
    TabPressedEvent,
)

from .pointer import movement
from .target import Focus, InputTarget, focused
from .wheel import FRAME_SECONDS, wheel_duration, wheel_progress

# Travel to the tab strip plus the press, then the way back into the page.
_TAB_PRESS_SECONDS = 0.45
_TAB_ENTER_SECONDS = 0.35

type Emit = Callable[[InputTarget, InputEvent], Awaitable[None]]


@dataclass(slots=True)
class _Rest:
    """Where the mouse last rested in one tab, as that tab's renderer saw it."""

    position: Point = field(default_factory=lambda: Point(x=0, y=0))
    # Last CSS cursor reported to viewers; None until the page has been asked.
    style: CursorStyle | None = None
    placed: bool = False


class Mouse:
    """The browser's one pointer.

    Each gesture goes to the tab that has focus when it starts, so a click or drag never
    splits across tabs. The mouse remembers where it last rested in each tab and returns
    there when that tab comes back to the front.
    """

    def __init__(self, focus: Focus, *, emit: Emit) -> None:
        self._focus = focus
        self._emit = emit
        self._rests: dict[str, _Rest] = {}

    @property
    def position(self) -> Point:
        return self._rest(focused(self._focus)).position

    def position_in(self, target_id: str) -> Point | None:
        """Where the mouse rests in a tab, or None before it has been there."""
        rest = self._rests.get(target_id)
        return rest.position if rest is not None and rest.placed else None

    def forget(self, target_id: str) -> None:
        """Drop the resting place of a closed tab."""
        self._rests.pop(target_id, None)

    async def switch_tab(
        self, gesture: TabGesture, tab_id: str, switch: Callable[[], Awaitable[None]]
    ) -> None:
        """Press a tab-strip control, let `switch` change focus, then return into the page.

        Without a focused tab there is nothing to leave: the pointer only appears in the
        new tab, near the center of its viewport the first time.
        """
        source = self._focus()
        if source is not None:
            position = self._rest(source).position
            await self._emit(
                source,
                TabPressedEvent(
                    gesture=gesture,
                    tab_id=tab_id,
                    from_position=(position.x, position.y),
                    duration=_TAB_PRESS_SECONDS,
                ),
            )
            await asyncio.sleep(_TAB_PRESS_SECONDS)
        await switch()
        target = focused(self._focus)
        rest = self._rest(target)
        if not rest.placed:
            width, height = await target.viewport_size()
            rest.position = Point(
                x=random.uniform(width * 0.4, width * 0.6),
                y=random.uniform(height * 0.4, height * 0.6),
            )
        if source is not None:
            position = rest.position
            await self._emit(
                target,
                CursorEnteredEvent(
                    to_position=(position.x, position.y), duration=_TAB_ENTER_SECONDS
                ),
            )
            await asyncio.sleep(_TAB_ENTER_SECONDS)
        # The renderer learns where the pointer is, so hover state matches the viewer.
        await self._dispatch(target, MouseEventKind.MOVED, rest.position)
        rest.placed = True
        await self._publish(target)

    async def publish_cursor(self) -> None:
        """Republish position and known cursor shape for viewers that attached late."""
        await self._publish(focused(self._focus))

    async def move_to(self, point: Point) -> None:
        await self._move(focused(self._focus), point)

    async def click(
        self,
        point: Point,
        *,
        count: Literal[1, 2] = 1,
        button: Literal["left", "right"] = "left",
    ) -> None:
        target = focused(self._focus)
        await self._move(target, point)
        mouse_button = MouseButton(button)
        buttons = 2 if button == "right" else 1
        for click_count in range(1, count + 1):
            try:
                await self._dispatch(
                    target,
                    MouseEventKind.PRESSED,
                    point,
                    button=mouse_button,
                    buttons=buttons,
                    click_count=click_count,
                )
            finally:
                await self._dispatch(
                    target,
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
        target = focused(self._focus)
        await self._move(target, start)
        current = start
        try:
            await self._dispatch(target, MouseEventKind.PRESSED, start, buttons=1, click_count=1)
            # CDP's mouse input handles native drag-and-drop as well as pointer gestures.
            steps = max(3, math.ceil(duration * 30))
            for index in range(1, steps + 1):
                fraction = index / steps
                current = Point(
                    x=start.x + (end.x - start.x) * fraction,
                    y=start.y + (end.y - start.y) * fraction,
                )
                await self._dispatch(target, MouseEventKind.MOVED, current, buttons=1)
                await asyncio.sleep(duration / steps)
            # Entering the drop target may only fire dragenter. Move again there so
            # its dragover handler can accept the drop before the button is released.
            await self._dispatch(target, MouseEventKind.MOVED, end, buttons=1)
        except BaseException:
            # Cancel a native drag before releasing so an interrupted gesture cannot drop.
            await target.cancel_drag()
            raise
        finally:
            await self._dispatch(target, MouseEventKind.RELEASED, current, buttons=0, click_count=1)

    async def scroll(
        self, *, delta_y: float, delta_x: float = 0, point: Point | None = None
    ) -> None:
        """Turn the wheel at `point`, or where the pointer already rests.

        The distance is spread over one wheel event per frame along Chrome's own smooth
        scroll curve, so the page scrolls like `scroll-behavior: smooth` but with real input.
        """
        if delta_y == 0 and delta_x == 0:
            return
        target = focused(self._focus)
        point = point or self._rest(target).position
        await self._move(target, point)
        duration = wheel_duration(math.hypot(delta_x, delta_y))
        clock = asyncio.get_running_loop()
        started = clock.time()
        sent = 0.0
        frame = 0
        while sent < 1:
            frame += 1
            await asyncio.sleep(max(0.0, started + frame * FRAME_SECONDS - clock.time()))
            # Follow the clock so slow dispatches do not stretch the scroll.
            elapsed = max(clock.time() - started, frame * FRAME_SECONDS)
            progress = wheel_progress(elapsed / duration) if elapsed < duration else 1.0
            if progress <= sent:
                continue
            await target.dispatch_wheel(
                point,
                delta_x=delta_x * (progress - sent),
                delta_y=delta_y * (progress - sent),
            )
            target.layout_changed()
            sent = progress
        await self._emit(
            target,
            ScrolledEvent(
                x=point.x, y=point.y, delta_x=delta_x, delta_y=delta_y, duration=duration
            ),
        )
        # Scrolled content can put a different element under the resting pointer.
        await self._refresh_style(target)

    async def _move(self, target: InputTarget, point: Point) -> None:
        path = movement(self._rest(target).position, point)
        cp1, cp2 = path.control_points
        await self._emit(
            target,
            CursorMovedEvent(
                from_position=(path.start.x, path.start.y),
                to_position=(point.x, point.y),
                control_point_1=cp1,
                control_point_2=cp2,
                duration=path.duration,
            ),
        )
        try:
            for step in range(1, path.steps + 1):
                current = path.point(step / path.steps)
                await self._dispatch(target, MouseEventKind.MOVED, current)
                if path.duration:
                    await asyncio.sleep(path.duration / path.steps)
        finally:
            await self._publish_position(target)
        await self._refresh_style(target)

    async def _publish(self, target: InputTarget) -> None:
        await self._publish_position(target)
        style = self._rest(target).style
        if style is not None:
            await self._emit(target, CursorStyleEvent(style=style))

    async def _publish_position(self, target: InputTarget) -> None:
        position = self._rest(target).position
        await self._emit(target, CursorStateEvent(x=position.x, y=position.y))

    async def _refresh_style(self, target: InputTarget) -> None:
        rest = self._rest(target)
        style = await target.cursor_style(rest.position)
        if style is not None and style != rest.style:
            rest.style = style
            await self._emit(target, CursorStyleEvent(style=style))

    async def _dispatch(
        self,
        target: InputTarget,
        kind: Literal[MouseEventKind.MOVED, MouseEventKind.PRESSED, MouseEventKind.RELEASED],
        point: Point,
        *,
        button: MouseButton = MouseButton.LEFT,
        buttons: int = 0,
        click_count: int = 0,
    ) -> None:
        await target.dispatch_mouse(
            kind,
            point,
            button=button if buttons or kind is MouseEventKind.RELEASED else MouseButton.NONE,
            buttons=buttons,
            click_count=click_count,
        )
        # The renderer now knows where the pointer is in this tab.
        rest = self._rest(target)
        rest.position, rest.placed = point, True
        target.layout_changed()
        if kind is MouseEventKind.MOVED:
            if buttons:
                await self._emit(target, CursorStateEvent(x=point.x, y=point.y, buttons=buttons))
            return
        event_type = PointerPressedEvent if kind is MouseEventKind.PRESSED else PointerReleasedEvent
        await self._emit(
            target, event_type(x=point.x, y=point.y, click_count=click_count, button=button.value)
        )

    def _rest(self, target: InputTarget) -> _Rest:
        return self._rests.setdefault(target.id, _Rest())
