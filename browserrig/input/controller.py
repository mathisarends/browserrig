from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from cdpify.domains.input import MouseButton

from browserrig.browser.models import Point
from browserrig.events import (
    CursorMovedEvent,
    CursorStateEvent,
    InputEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    ScrolledEvent,
)

from .keyboard import _TYPING_INTERVAL_SECONDS, _character, _key_stroke, _Stroke
from .pointer import ease, movement

if TYPE_CHECKING:
    from browserrig.browser.tab import Tab


class Input:
    def __init__(self, tab: Tab) -> None:
        self.tab = tab
        self.position = Point(x=0, y=0)
        self.action_id = ""

    @contextmanager
    def action(self, action_id: str):
        previous, self.action_id = self.action_id, action_id
        try:
            yield
        finally:
            self.action_id = previous

    async def emit(self, event: InputEvent) -> None:
        await self.tab.emit(replace(event, action_id=self.action_id))

    async def move_to(self, point: Point) -> None:
        path = movement(self.position, point)
        cp1, cp2 = path.control_points
        await self.emit(
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
                await self.mouse("mouseMoved", current)
                if path.duration:
                    await asyncio.sleep(path.duration / path.steps)
        finally:
            await self.emit(CursorStateEvent(x=self.position.x, y=self.position.y))

    async def mouse(
        self,
        kind: Literal["mouseMoved", "mousePressed", "mouseReleased"],
        point: Point,
        *,
        buttons: int = 0,
        click_count: int = 0,
    ) -> None:
        await self.tab.cdp.input.dispatch_mouse_event(
            type=kind,
            x=point.x,
            y=point.y,
            button=MouseButton.LEFT if buttons or kind == "mouseReleased" else MouseButton.NONE,
            buttons=buttons,
            click_count=click_count,
        )
        self.position = point
        if kind == "mouseMoved":
            if buttons:
                await self.emit(CursorStateEvent(x=point.x, y=point.y, buttons=buttons))
            return
        event_type = PointerPressedEvent if kind == "mousePressed" else PointerReleasedEvent
        await self.emit(event_type(x=point.x, y=point.y, click_count=click_count))

    async def scroll(self, *, point: Point, delta_y: float) -> None:
        if delta_y == 0:
            return
        await self.move_to(point)
        duration = min(0.4, max(0.08, abs(delta_y) * 0.0003))
        steps = max(3, round(duration * 60))
        previous = 0.0
        for index in range(1, steps + 1):
            current = delta_y * ease(index / steps)
            await self.tab.cdp.input.dispatch_mouse_event(
                type="mouseWheel", x=point.x, y=point.y, delta_x=0, delta_y=current - previous
            )
            previous = current
            await asyncio.sleep(duration / steps)
        await self.emit(
            ScrolledEvent(x=point.x, y=point.y, delta_x=0, delta_y=delta_y, duration=duration)
        )

    async def press_key(
        self,
        key: str,
        *,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> None:
        modifiers = tuple(
            name
            for enabled, name in (
                (hold_control, "Control"),
                (hold_shift, "Shift"),
                (hold_alt, "Alt"),
                (hold_meta, "Meta"),
            )
            if enabled
        )
        stroke = _key_stroke(key, modifiers)
        try:
            await self.emit(KeyboardVisibilityEvent(visible=True))
            await self._stroke(stroke)
        finally:
            await self.emit(KeyboardVisibilityEvent(visible=False))

    async def type_text(self, text: str) -> None:
        try:
            await self.emit(KeyboardVisibilityEvent(visible=True))
            # CRLF is one line break. Other Unicode characters are inserted unchanged.
            for value in text.replace("\r\n", "\n"):
                await self._stroke(_character(value), duration=_TYPING_INTERVAL_SECONDS)
                await asyncio.sleep(_TYPING_INTERVAL_SECONDS)
        finally:
            await self.emit(KeyboardVisibilityEvent(visible=False))

    async def _stroke(self, stroke: _Stroke, *, duration: float = 0) -> None:
        async with AsyncExitStack() as held:
            flags = 0
            for modifier in stroke.modifiers:
                arguments = _Stroke(modifier).arguments()
                held.push_async_callback(
                    self.tab.cdp.input.dispatch_key_event,
                    type="keyUp",
                    modifiers=flags,
                    **arguments,
                )
                flags |= _Stroke("", (modifier,)).flags
                await self.tab.cdp.input.dispatch_key_event(
                    type="rawKeyDown", modifiers=flags, **arguments
                )
            arguments = stroke.arguments()
            held.push_async_callback(
                self.tab.cdp.input.dispatch_key_event,
                type="keyUp",
                modifiers=flags,
                **arguments,
            )
            shortcut = any(modifier != "Shift" for modifier in stroke.modifiers)
            text = ""
            if not shortcut:
                text = {"Enter": "\r", "Tab": ""}.get(
                    stroke.key, stroke.key if len(stroke.key) == 1 else ""
                )
            # Separate rawKeyDown and char so text is inserted once, including
            # Unicode without a physical mapping. Enter keeps native semantics.
            await self.tab.cdp.input.dispatch_key_event(
                type="keyDown" if stroke.key == "Enter" and not shortcut else "rawKeyDown",
                modifiers=flags,
                text="\r" if stroke.key == "Enter" and not shortcut else "",
                **arguments,
            )
            if text and stroke.key != "Enter":
                await self.tab.cdp.input.dispatch_key_event(
                    type="char", modifiers=flags, text=text, **arguments
                )
        await self.emit(
            KeyPressedEvent(
                key=stroke.key,
                modifiers=stroke.modifiers,
                duration=duration,
            )
        )
