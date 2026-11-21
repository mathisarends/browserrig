import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from browserrig.core import Aim, Point

from .pointer import Bend, CursorPath, movement
from .wheel import WheelStep, scrolling

# Seconds between keys a person types, in the page and in the browser's own bars.
TYPING_INTERVAL_SECONDS = 0.05
# The middle of a target, as fractions of its visible box.
CENTER = Aim(0.5, 0.5)
_STRAIGHT = Bend(0, 0)


@dataclass(frozen=True, slots=True)
class KeyStroke:
    """One key of typed text: a character, or `Backspace` to erase the last one typed."""

    key: str
    # Seconds before the next key.
    delay_after: float = 0


class Motor(Protocol):
    """How the hand moves: typing rhythm, cursor routes, wheel steps, aim and clicks.

    The devices ask it how to perform input; what viewers see is the `Presenter`'s
    concern. Without one, input runs as fast as the page accepts it.
    """

    def keystrokes(self, text: str, *, sensitive: bool) -> Sequence[KeyStroke]:
        """The keys that type `text`, with the pause after each.

        A plan may slip and correct itself with `Backspace`, or leave a slip in place.
        Sensitive text must be typed exactly as given; only the pauses may vary.
        """
        ...

    def cursor_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        """Plan consecutive cursor strokes from `start` to `destination`.

        Stroke endpoints must meet. Stroke durations pace both free mouse
        movement and movement with the primary button held.
        """
        ...

    def aim_fractions(self, target_width: float, target_height: float) -> Aim:
        """Choose horizontal and vertical fractions within the target's visible box.

        A spot that something else covers falls back to the target's visible points.
        """
        ...

    def wheel_steps(self, *, delta_x: float, delta_y: float) -> Sequence[WheelStep]:
        """Plan wheel deltas and delays whose total matches the requested CSS pixels."""
        ...

    def press(self) -> float:
        """Seconds a mouse button stays down for one click."""
        ...

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        """Initial cursor position in viewport pixels; built-in motors use the center."""
        ...


class Instant:
    """Input at machine speed: no pauses, direct pointer moves, centered targets."""

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key) for key in text)

    def cursor_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return (CursorPath.curved(start, destination, 0, bend=_STRAIGHT),)

    def wheel_steps(self, *, delta_x: float, delta_y: float) -> Sequence[WheelStep]:
        return (WheelStep(delta_x=delta_x, delta_y=delta_y),)

    def aim_fractions(  # pylint: disable=unused-argument
        self, target_width: float, target_height: float
    ) -> Aim:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        return Point(x=viewport_width / 2, y=viewport_height / 2)


class HumanMotor:
    """Input at a person's pace: steady typing, eased cursor routes,
    smooth wheel gestures and clicks in the middle of a target.

    `scroll_speed` multiplies wheel speed: 2 halves its duration, 0.5 doubles it.
    """

    def __init__(
        self,
        *,
        typing_interval_seconds: float = TYPING_INTERVAL_SECONDS,
        scroll_speed: float = 1,
    ) -> None:
        _validate_pacing(typing_interval_seconds, scroll_speed)
        self._typing_interval_seconds = typing_interval_seconds
        self._scroll_speed = scroll_speed

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> Sequence[KeyStroke]:
        return tuple(KeyStroke(key, self._typing_interval_seconds) for key in text)

    def cursor_route(self, start: Point, destination: Point) -> Sequence[CursorPath]:
        return (movement(start, destination),)

    def wheel_steps(self, *, delta_x: float, delta_y: float) -> Sequence[WheelStep]:
        return scrolling(delta_x=delta_x, delta_y=delta_y, speed=self._scroll_speed)

    def aim_fractions(  # pylint: disable=unused-argument
        self, target_width: float, target_height: float
    ) -> Aim:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, viewport_width: float, viewport_height: float) -> Point:
        return Point(x=viewport_width / 2, y=viewport_height / 2)


def _validate_pacing(typing_interval_seconds: float, scroll_speed: float) -> None:
    if typing_interval_seconds < 0:
        raise ValueError("typing_interval_seconds must not be negative")
    if not math.isfinite(scroll_speed) or scroll_speed <= 0:
        raise ValueError("scroll_speed must be finite and positive")
