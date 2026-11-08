from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, Literal

from cdpify.domains.input import MouseButton

from browserrig.core import CursorStyle, MouseEventKind, Point
from browserrig.events import InputEvent
from browserrig.input import KeyEventType
from browserrig.scripts import CURSOR, CursorArgs

if TYPE_CHECKING:
    from .tab import Tab

# A cursor shape is presentation only and must never hold up input.
_CURSOR_PROBE_SECONDS = 0.25


class CdpInput:
    """Native input transport for the browser's devices, bound to one tab session.

    This adapter owns CDP dispatch and dialog handling; Mouse and Keyboard own
    gestures, device state and pacing.
    """

    def __init__(self, tab: Tab) -> None:
        self._tab = tab
        self.dialog_opened = asyncio.Event()

    @property
    def id(self) -> str:
        return self._tab.id

    async def viewport_size(self) -> tuple[float, float]:
        return await self._tab.viewport_size()

    def layout_changed(self) -> None:
        self._tab.layout_changed()

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
                button=button,
                buttons=buttons,
                click_count=click_count,
            )
        )

    async def dispatch_wheel(
        self, point: Point, *, delta_x: float, delta_y: float
    ) -> None:
        await self._input(
            self._tab.cdp.input.dispatch_mouse_event(
                type=MouseEventKind.WHEEL.value,  # smelt: ignore[SMT318] -- cdpify wants a Literal
                x=point.x,
                y=point.y,
                delta_x=delta_x,
                delta_y=delta_y,
            )
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
            opened = asyncio.ensure_future(self.dialog_opened.wait())
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
