from collections.abc import Callable
from typing import Literal, Protocol

from cdpify.domains.input import MouseButton

from browserrig.core import Point
from browserrig.core.errors import BrowserError
from browserrig.core.kinds import CursorStyle, MouseEventKind
from browserrig.events import InputEvent

type KeyEventType = Literal["keyDown", "keyUp", "rawKeyDown", "char"]


class InputTarget(Protocol):
    """A document that receives native input. The browser points its devices at the focused tab."""

    @property
    def id(self) -> str: ...

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
    ) -> None: ...

    async def dispatch_wheel(
        self, point: Point, *, delta_x: float, delta_y: float
    ) -> None: ...

    async def dispatch_key(
        self,
        kind: KeyEventType,
        *,
        modifiers: int,
        key: str,
        code: str,
        windows_virtual_key_code: int,
        text: str | None = None,
    ) -> None: ...

    async def cancel_drag(self) -> None: ...

    async def viewport_size(self) -> tuple[float, float]: ...

    async def cursor_style(self, point: Point) -> CursorStyle | None: ...

    def layout_changed(self) -> None: ...

    async def emit(self, event: InputEvent) -> None: ...


# The browser's currently focused tab, or None while no tab has focus.
type Focus = Callable[[], InputTarget | None]


def focused(focus: Focus) -> InputTarget:
    target = focus()
    if target is None:
        raise BrowserError("No active tab; open or explicitly activate one")
    return target
