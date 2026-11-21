from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, Literal

from cdpify.domains.input import MouseButton as CdpMouseButton
from cdpify.domains.input import TouchPoint

from browserrig.core import (
    BrowserError,
    CursorStyle,
    MouseEventKind,
    Point,
    ViewportSize,
)
from browserrig.events import InputEvent
from browserrig.input import (
    InputTarget,
    InputTargets,
    KeyEventType,
    MouseButton,
    TouchEventType,
)
from browserrig.scripts import CURSOR, CursorArgs

if TYPE_CHECKING:
    from .tab import Tab
    from .tabs import Tabs

# A cursor shape is presentation only and must never hold up input.
_CURSOR_PROBE_SECONDS = 0.25


class ChromeInputTargets(InputTargets):
    """Expose Chrome's focused transport without owning the input devices."""

    def __init__(self, tabs: Tabs) -> None:
        self._tabs = tabs

    def focused(self) -> InputTarget | None:
        tab = self._tabs.focused()
        return None if tab is None else tab.input


class CdpInput:
    """Native input transport for the browser's devices, bound to one tab session.

    This adapter owns CDP dispatch and dialog handling; Mouse and Keyboard own
    gestures, device state and pacing.
    """

    def __init__(self, tab: Tab) -> None:
        self._tab = tab
        self._dialog_opened = asyncio.Event()

    @property
    def id(self) -> str:
        return self._tab.id

    @property
    def document_id(self) -> str:
        return self._tab.document_id

    def dialog_opened(self) -> None:
        """Release input that waits for its reply because a dialog now holds it."""
        self._dialog_opened.set()

    def dialog_closed(self) -> None:
        self._dialog_opened.clear()

    async def viewport_size(self) -> ViewportSize:
        return await self._tab.viewport_size()

    def layout_changed(self) -> None:
        self._tab.invalidate_frames()

    async def emit(self, event: InputEvent) -> None:
        await self._tab.emit(event)

    async def cursor_style(self, point: Point) -> CursorStyle | None:
        """Return the CSS cursor under a viewport point, or None when the page cannot say."""
        if self._tab.dialog is not None:
            return None
        try:
            async with asyncio.timeout(_CURSOR_PROBE_SECONDS):
                frame = await self._tab.main_frame()
                style = await frame.run(CURSOR, CursorArgs(x=point.x, y=point.y))
        except Exception:  # pylint: disable=broad-exception-caught
            # Navigation, dialogs and detached sessions must not fail the input itself.
            return None
        return CursorStyle.parse(style)

    async def dispatch_mouse(
        self,
        kind: Literal[
            MouseEventKind.MOVED, MouseEventKind.PRESSED, MouseEventKind.RELEASED
        ],
        point: Point,
        *,
        button: MouseButton,
        buttons: int,
        click_count: int,
        modifiers: int = 0,
    ) -> None:
        await self._input(
            self._tab.cdp.input.dispatch_mouse_event(
                type=kind.value,
                x=point.x,
                y=point.y,
                modifiers=modifiers,
                button=CdpMouseButton(button),
                buttons=buttons,
                click_count=click_count,
            )
        )
        if kind is not MouseEventKind.MOVED or buttons:
            self._tab.invalidate_image_coordinates()

    async def dispatch_wheel(
        self, point: Point, *, delta_x: float, delta_y: float
    ) -> None:
        await self._input(
            self._tab.cdp.input.dispatch_mouse_event(
                type=MouseEventKind.WHEEL.value,  # smelt: ignore[MOD001] -- cdpify wants a Literal
                x=point.x,
                y=point.y,
                delta_x=delta_x,
                delta_y=delta_y,
            )
        )
        self._tab.invalidate_image_coordinates()

    async def check_touch_points(self, *points: Point) -> None:
        metrics = await self._tab.cdp.page.get_layout_metrics()
        visual = metrics.css_visual_viewport
        layout = metrics.css_layout_viewport
        # Snapshot geometry currently describes the layout viewport. Reject a
        # panned or clipped visual viewport before sending a contact at a wrong point.
        if (
            visual.offset_x
            or visual.offset_y
            or abs(layout.client_width - visual.client_width) > 1
            or abs(layout.client_height - visual.client_height) > 1
        ):
            raise BrowserError("Touch requires the full layout viewport to be visible")
        if any(
            point.x >= visual.client_width or point.y >= visual.client_height
            for point in points
        ):
            raise BrowserError("Touch point is outside the visible viewport")

    async def dispatch_touch(self, kind: TouchEventType, point: Point | None) -> None:
        points = [] if point is None else [TouchPoint(x=point.x, y=point.y, id=0)]
        self._tab.layout_changed()
        await self._input(
            self._tab.cdp.input.dispatch_touch_event(type=kind, touch_points=points)
        )

    async def dispatch_key(
        self,
        kind: KeyEventType,
        *,
        modifiers: int,
        key: str,
        code: str,
        windows_virtual_key_code: int,
        text: str | None = None,
    ) -> None:
        await self._input(
            self._tab.cdp.input.dispatch_key_event(
                type=kind,
                modifiers=modifiers,
                key=key,
                code=code,
                windows_virtual_key_code=windows_virtual_key_code,
                text=text,
            )
        )

    async def cancel_drag(self) -> None:
        await self._tab.cdp.input.cancel_dragging()

    async def _input(self, command: Coroutine[Any, Any, None]) -> None:
        """Send input, returning early when it opens a JavaScript dialog.

        Chrome answers an input event only after its handlers finish, and an alert, confirm
        or prompt holds them until the dialog closes. The input has landed by then, so the
        reply is left to arrive later.
        """
        if self._tab.dialog is not None:
            await command
            return
        # Started eagerly, input that needs no reply lands within the caller's step.
        sent = asyncio.Task(command, loop=asyncio.get_running_loop(), eager_start=True)
        if not sent.done():
            opened = asyncio.ensure_future(self._dialog_opened.wait())
            try:
                await asyncio.wait((sent, opened), return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                sent.cancel()
                raise
            finally:
                opened.cancel()
        if not sent.done():
            sent.add_done_callback(_discard_result)
            return
        sent.result()


def _discard_result(task: asyncio.Future[None]) -> None:
    # The reply of input that opened a dialog only reports when the dialog closed.
    if not task.cancelled():
        task.exception()
