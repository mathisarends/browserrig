"""Typed planner callbacks for independently paced input devices."""

from collections.abc import Callable, Sequence
from typing import Protocol

from browserrig.core import Aim, Point
from browserrig.input import CursorPath, KeyStroke, Motor, WheelStep, plan_drag


class KeystrokePlanner(Protocol):
    def __call__(self, text: str, /, *, sensitive: bool) -> Sequence[KeyStroke]:
        """Plan keys and pauses. Sensitive text must be typed exactly as supplied."""
        ...


type PointerRoutePlanner = Callable[[Point, Point], Sequence[CursorPath]]


def compose(
    base: Motor,
    keystrokes: KeystrokePlanner | None,
    pointer_route: PointerRoutePlanner | None,
) -> Motor:
    if keystrokes is None and pointer_route is None:
        return base
    return _PlannedMotor(
        base,
        base.keystrokes if keystrokes is None else keystrokes,
        base.pointer_route if pointer_route is None else pointer_route,
    )


class _PlannedMotor:
    def __init__(
        self,
        base: Motor,
        keystrokes: KeystrokePlanner,
        pointer_route: PointerRoutePlanner,
    ) -> None:
        self._base = base
        self._keystrokes = keystrokes
        self._pointer_route = pointer_route

    def keystrokes(self, text: str, *, sensitive: bool) -> Sequence[KeyStroke]:
        return self._keystrokes(text, sensitive=sensitive)

    def pointer_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return self._pointer_route(start, destination)

    def drag_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return plan_drag(self._base, start, destination)

    def aim_fractions(self, target_width: float, target_height: float) -> Aim:
        return self._base.aim_fractions(target_width, target_height)

    def wheel_steps(self, *, delta_x: float, delta_y: float) -> Sequence[WheelStep]:
        return self._base.wheel_steps(delta_x=delta_x, delta_y=delta_y)

    def press(self) -> float:
        return self._base.press()

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        return self._base.landing(viewport_width, viewport_height)
