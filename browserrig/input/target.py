from collections.abc import Callable
from typing import Literal, Protocol

from browserrig.core import (
    BrowserError,
    CursorStyle,
    MouseEventKind,
    Point,
    ViewportSize,
)
from browserrig.events import InputEvent

type KeyEventType = Literal["keyDown", "keyUp", "rawKeyDown", "char"]
type MouseButton = Literal["none", "left", "middle", "right", "back", "forward"]


class InputTarget(Protocol):
    """Transport for native input to a focused document, with cursor and event feedback.

    Implemented by the browser backend's input adapter, independently of its Tab API.
    """

    @property
    def id(self) -> str:
        """Identify the tab whose document receives input."""

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
        """Send a native mouse event at viewport CSS pixels with CDP button masks."""

    async def dispatch_wheel(
        self, point: Point, *, delta_x: float, delta_y: float
    ) -> None:
        """Send a wheel event at `point`, with deltas measured in CSS pixels."""

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
        """Send a native key event using CDP key codes and modifier masks."""

    async def cancel_drag(self) -> None:
        """Cancel a native drag still owned by the document."""

    async def viewport_size(self) -> ViewportSize:
        """Return the current viewport dimensions in CSS pixels."""

    async def cursor_style(self, point: Point) -> CursorStyle | None:
        """Read the cursor at viewport CSS pixels, or None when unavailable."""

    def layout_changed(self) -> None:
        """Invalidate cached frame geometry after input, including pointer movement."""

    async def emit(self, event: InputEvent) -> None:
        """Publish input feedback stamped with this target's browser and tab."""


# Transport for the browser's currently focused tab, or None while none has focus.
type Focus = Callable[[], InputTarget | None]


class InputTargets(Protocol):
    """The backend's focused input transport, independent of its browser API."""

    def focused(self) -> InputTarget | None:
        """Return the focused tab's transport, or None while no tab has focus."""


def focused(focus: Focus) -> InputTarget:
    target = focus()
    if target is None:
        raise BrowserError("No active tab; open or explicitly activate one")
    return target
