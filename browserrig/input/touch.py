import asyncio
import math
from contextlib import suppress
from typing import Literal, Protocol, runtime_checkable

from browserrig.core import BrowserError, Point

from .target import Focus, focused

_CANCEL_TIMEOUT_SECONDS = 2

type TouchEventType = Literal["touchStart", "touchMove", "touchEnd", "touchCancel"]


@runtime_checkable
class TouchTransport(Protocol):
    """Optional single-contact transport on an input target."""

    @property
    def id(self) -> str:
        """Identity of the addressed tab."""

    @property
    def document_id(self) -> str:
        """Identity of the current document in this target."""

    async def dispatch_touch(self, kind: TouchEventType, point: Point | None) -> None:
        """Send one active contact, or release/cancel all contacts."""

    async def check_touch_points(self, *points: Point) -> None:
        """Validate the gesture points against the live visible viewport."""


class Touch:
    """Dispatch complete single-finger gestures on one fixed target at a time."""

    def __init__(self, focus: Focus) -> None:
        self._focus = focus
        self._lock = asyncio.Lock()

    async def tap(self, point: Point) -> None:
        await self._gesture(point, None, 0)

    async def swipe(
        self, start: Point, end: Point, *, duration_seconds: float = 0.35
    ) -> None:
        if start == end or not 0.05 <= duration_seconds <= 5:
            raise BrowserError(
                "Swipe requires distinct endpoints and a duration of 0.05 to 5 seconds"
            )
        await self._gesture(start, end, duration_seconds)

    async def _gesture(
        self, start: Point, end: Point | None, duration_seconds: float
    ) -> None:
        target = focused(self._focus)
        if not isinstance(target, TouchTransport):
            raise BrowserError("The active input target does not support touch")
        document_id = target.document_id
        async with self._lock:
            await target.check_touch_points(start, end or start)
            self._check_focus(target, document_id)
            try:
                await target.dispatch_touch("touchStart", start)
                if end is not None:
                    await self._move(
                        target,
                        document_id,
                        start,
                        end,
                        duration_seconds=duration_seconds,
                    )
                self._check_focus(target, document_id)
                await target.dispatch_touch("touchEnd", None)
            except BaseException:
                # The start may already have landed, even if its reply was interrupted.
                with suppress(Exception):
                    await asyncio.wait_for(
                        target.dispatch_touch("touchCancel", None),
                        timeout=_CANCEL_TIMEOUT_SECONDS,
                    )
                raise

    async def _move(
        self,
        target: TouchTransport,
        document_id: str,
        start: Point,
        end: Point,
        *,
        duration_seconds: float,
    ) -> None:
        steps = max(2, math.ceil(duration_seconds * 30))
        loop = asyncio.get_running_loop()
        began = loop.time()
        for index in range(1, steps + 1):
            fraction = index / steps
            await asyncio.sleep(
                max(0, began + fraction * duration_seconds - loop.time())
            )
            self._check_focus(target, document_id)
            point = Point(
                x=start.x + fraction * (end.x - start.x),
                y=start.y + fraction * (end.y - start.y),
            )
            await target.dispatch_touch("touchMove", point)

    def _check_focus(self, target: TouchTransport, document_id: str) -> None:
        active = self._focus()
        if (
            active is None
            or active.id != target.id
            or target.document_id != document_id
        ):
            raise BrowserError("The focused tab or document changed during touch input")
